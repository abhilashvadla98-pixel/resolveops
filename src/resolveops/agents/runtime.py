from typing import Protocol

from resolveops.agents.budgets import AgentBudgetExceeded, BudgetLedger
from resolveops.agents.context import AgentContextBuilder
from resolveops.agents.invocation import AgentInvoker
from resolveops.agents.models import (
    AgentDomain,
    AgentRole,
    CriticDecision,
    CriticReport,
    InvestigationTurn,
    MultiAgentReasoningResult,
    PolicyTurn,
    ResolutionProposal,
    SupervisorPlan,
    ToolCallStatus,
    ToolRequest,
)
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.skills import skill_for_role
from resolveops.agents.tools import AgentToolResult
from resolveops.memory.retrieval import (
    ReviewedMemoryRetriever,
    issue_types_from_tool_results,
    select_applicable_memories,
)
from resolveops.observability.metrics import record_agent_tool_call


class AgentToolExecutor(Protocol):
    def execute(self, role: AgentRole, request: ToolRequest) -> AgentToolResult: ...


class MultiAgentReasoningRuntime:
    def __init__(
        self,
        *,
        invoker: AgentInvoker,
        tools: AgentToolExecutor,
        run_store: AgentRunStore,
        ledger: BudgetLedger,
        context_builder: AgentContextBuilder | None = None,
        max_investigation_turns: int = 4,
        max_policy_turns: int = 3,
        memory_retriever: ReviewedMemoryRetriever | None = None,
    ) -> None:
        if not 1 <= max_investigation_turns <= 10:
            raise ValueError("investigation turns must be between 1 and 10")
        if not 1 <= max_policy_turns <= 10:
            raise ValueError("policy turns must be between 1 and 10")
        self.invoker = invoker
        self.tools = tools
        self.run_store = run_store
        self.ledger = ledger
        self.context_builder = context_builder or AgentContextBuilder()
        self.max_investigation_turns = max_investigation_turns
        self.max_policy_turns = max_policy_turns
        self.memory_retriever = memory_retriever

    def run(
        self,
        *,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        domain: AgentDomain,
        objective: str,
        trace_id: str,
    ) -> MultiAgentReasoningResult:
        run_ids: list[str] = []
        base = self._context(
            role=AgentRole.SUPERVISOR,
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            facts=[{"domain": domain.value, "case_id": case_id}],
        )
        supervisor, supervisor_run = self.invoker.invoke(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            role=AgentRole.SUPERVISOR,
            context=base,
            response_model=SupervisorPlan,
        )
        run_ids.append(supervisor_run)
        investigation, investigation_results, investigation_runs = self.investigate(
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            trace_id=trace_id,
            supervisor=supervisor,
            parent_run_id=supervisor_run,
        )
        run_ids.extend(investigation_runs)
        policy, policy_results, policy_runs = self.research_policy(
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            trace_id=trace_id,
            supervisor=supervisor,
            investigation=investigation,
            parent_run_id=supervisor_run,
        )
        run_ids.extend(policy_runs)
        memory_results = self.reviewed_memory_context(
            tenant_id=tenant_id,
            investigation_results=investigation_results,
            policy=policy,
        )
        resolution_context = self._context(
            role=AgentRole.RESOLUTION,
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            facts=[investigation.model_dump(mode="json")],
            prior_outputs=[supervisor.model_dump(mode="json")],
            tool_results=[item.model_dump(mode="json") for item in investigation_results],
            policy_results=[item.model_dump(mode="json") for item in policy_results],
            memory_results=memory_results,
        )
        resolution, resolution_run = self.invoker.invoke(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            role=AgentRole.RESOLUTION,
            context=resolution_context,
            response_model=ResolutionProposal,
            parent_agent_run_id=supervisor_run,
        )
        run_ids.append(resolution_run)
        critic, critic_run = self.criticize(
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            trace_id=trace_id,
            investigation=investigation,
            policy=policy,
            resolution=resolution,
            parent_run_id=supervisor_run,
        )
        run_ids.append(critic_run)

        replan_count = 0
        if critic.decision == CriticDecision.REVISE and self.ledger.budget.max_replans > 0:
            replan_count = 1
            replan_context = self._context(
                role=AgentRole.SUPERVISOR,
                workflow_id=workflow_id,
                case_id=case_id,
                tenant_id=tenant_id,
                objective=objective,
                facts=[investigation.model_dump(mode="json")],
                prior_outputs=[
                    supervisor.model_dump(mode="json"),
                    resolution.model_dump(mode="json"),
                    critic.model_dump(mode="json"),
                ],
            )
            supervisor, replan_run = self.invoker.invoke(
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                trace_id=trace_id,
                role=AgentRole.SUPERVISOR,
                context=replan_context,
                response_model=SupervisorPlan,
                parent_agent_run_id=supervisor_run,
            )
            run_ids.append(replan_run)

        return MultiAgentReasoningResult(
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            domain=domain,
            supervisor=supervisor,
            investigation=investigation,
            policy=policy,
            resolution=resolution,
            critic=critic,
            status=(
                "ready_for_control_plane"
                if critic.decision == CriticDecision.ACCEPT
                else "escalated"
            ),
            replan_count=replan_count,
            agent_call_count=self.ledger.usage.model_calls,
            tool_call_count=self.ledger.usage.tool_calls,
            usage=self.ledger.usage,
            agent_run_ids=run_ids,
        )

    def verify_after_execution(
        self,
        *,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        objective: str,
        trace_id: str,
        expected_resolution: ResolutionProposal,
        fresh_state: dict[str, object],
        parent_agent_run_id: str | None = None,
    ) -> tuple[CriticReport, str]:
        context = self._context(
            role=AgentRole.CRITIC,
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            facts=[{"fresh_state": fresh_state}],
            prior_outputs=[expected_resolution.model_dump(mode="json")],
        )
        return self.invoker.invoke(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            role=AgentRole.CRITIC,
            context=context,
            response_model=CriticReport,
            parent_agent_run_id=parent_agent_run_id,
        )

    def investigate(
        self,
        *,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        objective: str,
        trace_id: str,
        supervisor: SupervisorPlan,
        parent_run_id: str,
    ) -> tuple[InvestigationTurn, list[AgentToolResult], list[str]]:
        results: list[AgentToolResult] = []
        runs: list[str] = []
        turn: InvestigationTurn | None = None
        for _ in range(self.max_investigation_turns):
            context = self._context(
                role=AgentRole.INVESTIGATION,
                workflow_id=workflow_id,
                case_id=case_id,
                tenant_id=tenant_id,
                objective=objective,
                facts=[{"case_id": case_id}],
                prior_outputs=[supervisor.model_dump(mode="json")],
                tool_results=[item.model_dump(mode="json") for item in results],
                required_evidence=list(supervisor.required_evidence),
            )
            turn, run_id = self.invoker.invoke(
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                trace_id=trace_id,
                role=AgentRole.INVESTIGATION,
                context=context,
                response_model=InvestigationTurn,
                parent_agent_run_id=parent_run_id,
            )
            runs.append(run_id)
            if turn.complete:
                if (
                    not turn.facts
                    or not turn.evidence_ids
                    or not turn.source_provenance
                    or turn.missing_evidence
                    or any(not fact.fresh for fact in turn.facts)
                ):
                    raise ValueError(
                        "completed investigation requires fresh evidence, provenance, and no gaps"
                    )
                return turn, results, runs
            if turn.next_tool is None:
                break
            results.append(
                self._execute_tool(
                    tenant_id=tenant_id,
                    role=AgentRole.INVESTIGATION,
                    run_id=run_id,
                    request=turn.next_tool,
                )
            )
        if turn is None:
            raise RuntimeError("investigation did not start")
        raise AgentBudgetExceeded("investigation_turn_limit_exceeded")

    def research_policy(
        self,
        *,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        objective: str,
        trace_id: str,
        supervisor: SupervisorPlan,
        investigation: InvestigationTurn,
        parent_run_id: str,
    ) -> tuple[PolicyTurn, list[AgentToolResult], list[str]]:
        results: list[AgentToolResult] = []
        runs: list[str] = []
        turn: PolicyTurn | None = None
        for _ in range(self.max_policy_turns):
            context = self._context(
                role=AgentRole.POLICY,
                workflow_id=workflow_id,
                case_id=case_id,
                tenant_id=tenant_id,
                objective=objective,
                facts=[investigation.model_dump(mode="json")],
                prior_outputs=[supervisor.model_dump(mode="json")],
                policy_results=[item.model_dump(mode="json") for item in results],
            )
            turn, run_id = self.invoker.invoke(
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                trace_id=trace_id,
                role=AgentRole.POLICY,
                context=context,
                response_model=PolicyTurn,
                parent_agent_run_id=parent_run_id,
            )
            runs.append(run_id)
            if turn.complete:
                if not turn.missing_policy and (not turn.citations or not turn.policy_versions):
                    raise ValueError(
                        "completed policy research requires citations and policy versions"
                    )
                return turn, results, runs
            if turn.next_query is None:
                break
            request = ToolRequest(
                tool_name="search_policies",
                arguments={"query": turn.next_query, "top_k": "5"},
                purpose="Retrieve active policy evidence for the case",
            )
            results.append(
                self._execute_tool(
                    tenant_id=tenant_id,
                    role=AgentRole.POLICY,
                    run_id=run_id,
                    request=request,
                )
            )
        if turn is None:
            raise RuntimeError("policy research did not start")
        raise AgentBudgetExceeded("policy_turn_limit_exceeded")

    def criticize(
        self,
        *,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        objective: str,
        trace_id: str,
        investigation: InvestigationTurn,
        policy: PolicyTurn,
        resolution: ResolutionProposal,
        parent_run_id: str,
    ) -> tuple[CriticReport, str]:
        context = self._context(
            role=AgentRole.CRITIC,
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            facts=[investigation.model_dump(mode="json")],
            prior_outputs=[
                policy.model_dump(mode="json"),
                resolution.model_dump(mode="json"),
            ],
            policy_results=[policy.model_dump(mode="json")],
        )
        return self.invoker.invoke(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            role=AgentRole.CRITIC,
            context=context,
            response_model=CriticReport,
            parent_agent_run_id=parent_run_id,
        )

    def reviewed_memory_context(
        self,
        *,
        tenant_id: str,
        investigation_results: list[AgentToolResult],
        policy: PolicyTurn,
    ) -> list[dict[str, object]]:
        if self.memory_retriever is None:
            return []
        serialized_results = [item.model_dump(mode="json") for item in investigation_results]
        issue_types = issue_types_from_tool_results(serialized_results)
        memories = select_applicable_memories(
            self.memory_retriever,
            tenant_id=tenant_id,
            issue_types=issue_types,
            current_policy_versions=dict(policy.policy_versions),
        )
        return [
            {
                "memory_id": memory.memory_id,
                "tenant_id": memory.tenant_id,
                "issue_type": memory.issue_type,
                "evidence_pattern": list(memory.evidence_pattern),
                "policy_versions": dict(memory.policy_versions),
                "approved_resolution": memory.approved_resolution.model_dump(mode="json"),
                "verification_outcome": memory.verification_outcome,
                "advisory_only": True,
                "source": "human_reviewed_resolution_memory",
            }
            for memory in memories
        ]

    def _execute_tool(
        self,
        *,
        tenant_id: str,
        role: AgentRole,
        run_id: str,
        request: ToolRequest,
    ) -> AgentToolResult:
        skill = skill_for_role(role)
        if skill is None or request.tool_name not in skill.allowed_tools:
            raise PermissionError(
                f"tool {request.tool_name} is outside the declared {role.value} skill boundary"
            )
        self.ledger.consume_tool_call()
        record = self.run_store.start_tool_call(
            tenant_id=tenant_id,
            agent_run_id=run_id,
            tool_name=request.tool_name,
            arguments=dict(request.arguments),
        )
        try:
            result = self.tools.execute(role, request)
        except Exception as exc:
            self.run_store.finish_tool_call(
                record.tool_call_id,
                status=ToolCallStatus.FAILED,
                error_classification=type(exc).__name__,
            )
            record_agent_tool_call(request.tool_name, "failed")
            raise
        self.run_store.finish_tool_call(
            record.tool_call_id,
            status=ToolCallStatus.COMPLETED,
            result_category=result.result_category,
        )
        record_agent_tool_call(request.tool_name, "completed")
        return result

    def _context(self, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.context_builder.build(**kwargs)  # type: ignore[arg-type]

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from resolveops.agents.budgets import AgentBudgetExceeded, BudgetLedger
from resolveops.agents.context import AgentContext, AgentContextBuilder
from resolveops.agents.grounding import (
    ground_investigation,
    ground_policy,
    observation_context,
    validate_resolution_references,
)
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
    ToolArguments,
    ToolCallStatus,
    ToolRequest,
)
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.skills import skill_for_role
from resolveops.agents.tools import AgentReadToolRegistry, AgentToolResult, argument_contracts
from resolveops.memory.retrieval import (
    ReviewedMemoryRetriever,
    issue_types_from_tool_results,
    select_applicable_memories,
)
from resolveops.observability.metrics import record_agent_tool_call
from resolveops.reasoning.errors import ReasoningProviderError


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
        context_tool_allowlists: dict[AgentRole, list[str]] | None = None,
        clock: Callable[[], datetime] | None = None,
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
        self.context_tool_allowlists = context_tool_allowlists or {}
        self.clock = clock or (lambda: datetime.now(UTC))
        self.validation_repair_used = False
        for role, role_tools in self.context_tool_allowlists.items():
            skill = skill_for_role(role)
            declared = set(skill.allowed_tools) if skill is not None else set()
            if not set(role_tools).issubset(declared):
                raise ValueError(f"context tool allowlist exceeds the declared {role.value} skill")

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
        if investigation.contradictions:
            return MultiAgentReasoningResult(
                workflow_id=workflow_id,
                case_id=case_id,
                tenant_id=tenant_id,
                domain=domain,
                supervisor=supervisor,
                investigation=investigation,
                policy=None,
                resolution=None,
                critic=None,
                skipped_roles=[AgentRole.POLICY, AgentRole.RESOLUTION, AgentRole.CRITIC],
                stop_reason="Investigation reported contradictory source evidence; operator review is required.",
                status="escalated",
                replan_count=0,
                agent_call_count=self.ledger.usage.model_calls,
                tool_call_count=self.ledger.usage.tool_calls,
                usage=self.ledger.usage,
                agent_run_ids=run_ids,
            )
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
        if policy.missing_policy or policy.conflicts:
            return MultiAgentReasoningResult(
                workflow_id=workflow_id,
                case_id=case_id,
                tenant_id=tenant_id,
                domain=domain,
                supervisor=supervisor,
                investigation=investigation,
                policy=policy,
                resolution=None,
                critic=None,
                skipped_roles=[AgentRole.RESOLUTION, AgentRole.CRITIC],
                stop_reason="Active policy is missing or conflicting; remaining model calls were skipped.",
                status="escalated",
                replan_count=0,
                agent_call_count=self.ledger.usage.model_calls,
                tool_call_count=self.ledger.usage.tool_calls,
                usage=self.ledger.usage,
                agent_run_ids=run_ids,
            )
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
            prior_outputs=[supervisor.model_dump(mode="json"), policy.model_dump(mode="json")],
            tool_results=[observation_context(item) for item in investigation_results],
            policy_results=[item.model_dump(mode="json") for item in policy_results],
            memory_results=memory_results,
            valid_evidence_ids=list(investigation.evidence_ids),
            valid_policy_citation_ids=list(policy.citations),
        )
        resolution, resolution_runs = self.resolve_with_validation(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            context=resolution_context,
            investigation=investigation,
            policy=policy,
            parent_run_id=supervisor_run,
        )
        run_ids.extend(resolution_runs)
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
        if isinstance(self.tools, AgentReadToolRegistry):
            self.tools.bind_case_scope(case_id)
        results: list[AgentToolResult] = []
        runs: list[str] = []
        turn: InvestigationTurn | None = None
        rejected_turns: list[dict[str, object]] = []
        validation_feedback: list[str] = []
        for turn_number in range(self.max_investigation_turns):
            source_requirements: list[str] = []
            if isinstance(self.tools, AgentReadToolRegistry):
                try:
                    self.tools.require_investigation_coverage(results)
                except ValueError as exc:
                    # This is derived from scoped source links, not scorer labels or
                    # an answer. Surface missing reads before a premature completion.
                    source_requirements.append(str(exc))
            context = self._context(
                role=AgentRole.INVESTIGATION,
                workflow_id=workflow_id,
                case_id=case_id,
                tenant_id=tenant_id,
                objective=objective,
                facts=[
                    {
                        "case_id": case_id,
                        "investigation_turns_remaining": self.max_investigation_turns - turn_number,
                    }
                ],
                prior_outputs=[supervisor.model_dump(mode="json"), *rejected_turns],
                tool_results=[observation_context(item) for item in results],
                required_evidence=[
                    *supervisor.required_evidence,
                    *source_requirements,
                    *validation_feedback,
                ],
            )
            try:
                turn, run_id = self.invoker.invoke(
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    trace_id=trace_id,
                    role=AgentRole.INVESTIGATION,
                    context=context,
                    response_model=InvestigationTurn,
                    parent_agent_run_id=parent_run_id,
                )
            except ReasoningProviderError as exc:
                if exc.code != "agent_output_invalid" or self.validation_repair_used:
                    raise
                self.validation_repair_used = True
                # This is an additional persisted invocation within the same overall
                # ledger. Feedback states the schema failure, never an expected answer.
                context = context.model_copy(
                    update={
                        "required_evidence": [
                            *context.required_evidence,
                            f"Your preceding response failed schema validation: {exc.message[:500]}",
                        ]
                    }
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
                try:
                    turn = ground_investigation(turn, results, now=self.clock())
                    if isinstance(self.tools, AgentReadToolRegistry):
                        self.tools.require_investigation_coverage(results)
                except ValueError as exc:
                    if turn_number + 1 < self.max_investigation_turns:
                        rejected_turns.append(turn.model_dump(mode="json"))
                        validation_feedback = [f"Previous output rejected: {exc}"]
                        continue
                    raise
                return turn, results, runs
            if turn.next_tool is None:
                break
            scoped_request = self._bind_primary_scope(turn.next_tool, case_id)
            results.append(
                self._execute_tool(
                    tenant_id=tenant_id,
                    role=AgentRole.INVESTIGATION,
                    run_id=run_id,
                    request=scoped_request,
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
        rejected_turns: list[dict[str, object]] = []
        for turn_number in range(self.max_policy_turns):
            context = self._context(
                role=AgentRole.POLICY,
                workflow_id=workflow_id,
                case_id=case_id,
                tenant_id=tenant_id,
                objective=objective,
                facts=[investigation.model_dump(mode="json")],
                prior_outputs=[supervisor.model_dump(mode="json"), *rejected_turns],
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
                if not results:
                    request = ToolRequest(
                        tool_name="search_policies",
                        arguments=ToolArguments(query=objective, top_k=5),
                        purpose="Retrieve active policy evidence before completing the assessment",
                    )
                    results.append(
                        self._execute_tool(
                            tenant_id=tenant_id,
                            role=AgentRole.POLICY,
                            run_id=run_id,
                            request=request,
                        )
                    )
                    continue
                try:
                    turn = ground_policy(turn, results, now=self.clock())
                except ValueError as exc:
                    if turn_number + 1 < self.max_policy_turns:
                        rejected_turns.append(
                            {**turn.model_dump(mode="json"), "validation_error": str(exc)}
                        )
                        continue
                    raise
                return turn, results, runs
            if turn.next_query is None:
                break
            request = ToolRequest(
                tool_name="search_policies",
                arguments=ToolArguments(query=turn.next_query, top_k=5),
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

    @staticmethod
    def _ground_policy_turn(turn: PolicyTurn, results: list[AgentToolResult]) -> PolicyTurn:
        return ground_policy(turn, results)

    def resolve_with_validation(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        trace_id: str,
        context: AgentContext,
        investigation: InvestigationTurn,
        policy: PolicyTurn,
        parent_run_id: str,
    ) -> tuple[ResolutionProposal, list[str]]:
        """One shared repair may explain a rejected reference, never the correct answer."""
        runs: list[str] = []
        for attempt in range(2):
            try:
                proposal, run_id = self.invoker.invoke(
                    tenant_id=tenant_id,
                    workflow_id=workflow_id,
                    trace_id=trace_id,
                    role=AgentRole.RESOLUTION,
                    context=context,
                    response_model=ResolutionProposal,
                    parent_agent_run_id=parent_run_id,
                )
                runs.append(run_id)
                validate_resolution_references(proposal, investigation, policy)
                return proposal, runs
            except (ValueError, ReasoningProviderError) as exc:
                if isinstance(exc, ReasoningProviderError) and exc.code != "agent_output_invalid":
                    raise
                if attempt or self.validation_repair_used:
                    raise
                self.validation_repair_used = True
                # The first invocation and every consumed token remain persisted.
                # Registries come from grounded reads, not scorer expectations.
                context = context.model_copy(
                    update={
                        "required_evidence": [
                            *context.required_evidence,
                            (
                                f"Your preceding proposal failed validation: {str(exc)[:500]}. "
                                "Use only valid_evidence_ids and valid_policy_citation_ids for references."
                            ),
                        ],
                    }
                )
        raise RuntimeError("resolution validation did not finish")

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
            valid_evidence_ids=list(investigation.evidence_ids),
            valid_policy_citation_ids=list(policy.citations),
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
            arguments=request.arguments.model_dump(mode="json", exclude_none=True),
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

    @staticmethod
    def _bind_primary_scope(request: ToolRequest, case_id: str) -> ToolRequest:
        """Bind primary-case reads in code; the model cannot select another case."""
        if request.tool_name == "get_case":
            return request.model_copy(update={"arguments": ToolArguments(case_id=case_id)})
        if request.tool_name == "get_it_snapshot":
            return request.model_copy(update={"arguments": ToolArguments(it_case_id=case_id)})
        return request

    def _context(self, **kwargs: object):  # type: ignore[no-untyped-def]
        if hasattr(self, "clock"):
            kwargs.setdefault("now", self.clock())
        role = kwargs.get("role")
        if isinstance(role, AgentRole) and "allowed_tools" not in kwargs:
            skill = skill_for_role(role)
            declared = list(skill.allowed_tools) if skill is not None else []
            kwargs["allowed_tools"] = self.context_tool_allowlists.get(role, declared)
        allowed_tools = kwargs.get("allowed_tools")
        if isinstance(allowed_tools, list) and "tool_contracts" not in kwargs:
            kwargs["tool_contracts"] = argument_contracts(allowed_tools)
        return self.context_builder.build(**kwargs)  # type: ignore[arg-type]

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

ALLOWED_CHECKPOINT_TYPES = [
    ("resolveops.agents.models", "AgentBudgetUsage"),
    ("resolveops.agents.models", "AgentDomain"),
    ("resolveops.agents.models", "AgentRole"),
    ("resolveops.agents.models", "CriticDecision"),
    ("resolveops.agents.models", "CriticReport"),
    ("resolveops.agents.models", "EvidenceFact"),
    ("resolveops.agents.models", "InvestigationTurn"),
    ("resolveops.agents.models", "IssueResolution"),
    ("resolveops.agents.models", "MultiAgentReasoningResult"),
    ("resolveops.agents.models", "PlanStep"),
    ("resolveops.agents.models", "PolicyTurn"),
    ("resolveops.agents.models", "ProposedAction"),
    ("resolveops.agents.models", "ResolutionProposal"),
    ("resolveops.agents.models", "SupervisorPlan"),
    ("resolveops.models.case", "CaseIssueType"),
    ("resolveops.models.case", "IssueFinding"),
    ("resolveops.models.refund", "RefundKind"),
    ("resolveops.operations.models", "Actor"),
    ("resolveops.operations.models", "ActorRole"),
    ("resolveops.operations.models", "IssueRefundRequest"),
    ("resolveops.operations.models", "OperationResult"),
    ("resolveops.operations.models", "OperationStatus"),
    ("resolveops.operations.models", "OperationType"),
    ("resolveops.reasoning.models", "ReasoningAssessment"),
    ("resolveops.reasoning.models", "ReasoningDisposition"),
    ("resolveops.reasoning.models", "ReasoningPolicyExcerpt"),
    ("resolveops.reasoning.models", "ReasoningTrace"),
    ("resolveops.workflows.models", "ApprovalStatus"),
    ("resolveops.workflows.models", "PolicyCitation"),
    ("resolveops.workflows.models", "WorkflowApproval"),
    ("resolveops.workflows.models", "WorkflowDecision"),
    ("resolveops.workflows.models", "WorkflowOutcome"),
    ("resolveops.workflows.models", "WorkflowStatus"),
]


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=ALLOWED_CHECKPOINT_TYPES,
    )


def postgres_checkpoint_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("durable checkpoints require a PostgreSQL database URL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@contextmanager
def open_postgres_checkpointer(database_url: str, *, setup: bool = True) -> Iterator[PostgresSaver]:
    """Open a strict, production PostgreSQL LangGraph checkpointer."""
    serializer = checkpoint_serializer()
    connection_url = postgres_checkpoint_url(database_url)
    with psycopg.connect(
        connection_url,
        autocommit=True,
        row_factory=dict_row,
    ) as connection:
        checkpointer = PostgresSaver(connection, serde=serializer)
        if setup:
            checkpointer.setup()
        yield checkpointer

from enum import Enum

from pydantic import Field

from resolveops.models.common import (
    AwareDatetime,
    CurrencyCode,
    DomainModel,
    Identifier,
    NonEmptyText,
    PositiveAmount,
)
from resolveops.models.notification import NotificationChannel
from resolveops.models.refund import RefundKind


class ActorRole(str, Enum):
    AGENT = "agent"
    OPERATOR = "operator"
    APPROVER = "approver"
    SYSTEM = "system"


class Permission(str, Enum):
    READ_OPERATIONS = "read_operations"
    READ_PII = "read_pii"
    ISSUE_REFUND = "issue_refund"
    SEND_NOTIFICATION = "send_notification"
    CREATE_TICKET = "create_ticket"
    GRANT_REPOSITORY_ACCESS = "grant_repository_access"


class OperationType(str, Enum):
    ISSUE_REFUND = "issue_refund"
    SEND_NOTIFICATION = "send_notification"
    CREATE_TICKET = "create_ticket"
    GRANT_REPOSITORY_ACCESS = "grant_repository_access"


class OperationStatus(str, Enum):
    STARTED = "started"
    EXECUTED = "executed"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFICATION_FAILED = "verification_failed"


class AuditEventType(str, Enum):
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    FAILED = "failed"
    EXECUTED = "executed"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"


class ReliabilityEventType(str, Enum):
    ATTEMPT_STARTED = "attempt_started"
    RETRY_SCHEDULED = "retry_scheduled"
    ATTEMPT_SUCCEEDED = "attempt_succeeded"
    LEASE_RECOVERED = "lease_recovered"
    VERIFICATION_ATTEMPTED = "verification_attempted"
    VERIFICATION_RETRY_SCHEDULED = "verification_retry_scheduled"
    RECOVERY_VERIFIED = "recovery_verified"
    COMPENSATION_REQUIRED = "compensation_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class RecoveryDisposition(str, Enum):
    COMPLETE = "complete"
    WAIT_FOR_LEASE = "wait_for_lease"
    RETRY_EXECUTION = "retry_execution"
    VERIFY_ONLY = "verify_only"
    MANUAL_REVIEW = "manual_review"


class CompensationStrategy(str, Enum):
    NONE = "none"
    TRANSACTION_ROLLBACK = "transaction_rollback"
    PROVIDER_IDEMPOTENCY = "provider_idempotency"
    MANUAL = "manual"


class Actor(DomainModel):
    actor_id: Identifier
    role: ActorRole


class IssueRefundRequest(DomainModel):
    idempotency_key: Identifier
    case_id: Identifier
    issue_id: Identifier
    payment_id: Identifier
    amount: PositiveAmount
    currency: CurrencyCode
    kind: RefundKind
    reason: NonEmptyText
    return_id: Identifier | None = None


class SendNotificationRequest(DomainModel):
    idempotency_key: Identifier
    case_id: Identifier
    customer_id: Identifier
    channel: NotificationChannel
    recipient: NonEmptyText
    message: NonEmptyText


class CreateTicketRequest(DomainModel):
    idempotency_key: Identifier
    case_id: Identifier
    subject: NonEmptyText
    description: NonEmptyText


class OperationResult(DomainModel):
    operation_id: Identifier
    operation_type: OperationType
    resource_id: Identifier
    status: OperationStatus
    verified: bool
    idempotent_replay: bool = False


class AuditEvent(DomainModel):
    audit_event_id: Identifier
    operation_id: Identifier
    sequence_number: int
    event_type: AuditEventType
    actor_id: Identifier
    actor_role: ActorRole
    case_id: Identifier | None = None
    issue_id: Identifier | None = None
    resource_type: str | None = None
    resource_id: Identifier | None = None
    details: dict[str, object]
    occurred_at: AwareDatetime


class ReliabilityEvent(DomainModel):
    reliability_event_id: Identifier
    operation_id: Identifier
    sequence_number: int = Field(gt=0)
    event_type: ReliabilityEventType
    attempt_number: int | None = Field(default=None, gt=0)
    details: dict[str, object]
    occurred_at: AwareDatetime


class OperationRecoveryPlan(DomainModel):
    operation_id: Identifier
    idempotency_key: Identifier
    status: OperationStatus
    disposition: RecoveryDisposition
    compensation: CompensationStrategy
    safe_to_retry: bool
    attempt_count: int = Field(ge=0)
    verification_attempt_count: int = Field(ge=0)
    max_attempts: int = Field(gt=0)
    lease_expires_at: AwareDatetime | None = None
    next_attempt_at: AwareDatetime | None = None
    reason: NonEmptyText

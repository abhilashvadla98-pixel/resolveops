from enum import Enum

from pydantic import model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class NotificationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"


class NotificationStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Notification(DomainModel):
    notification_id: Identifier
    case_id: Identifier
    customer_id: Identifier
    channel: NotificationChannel
    recipient: NonEmptyText
    message: NonEmptyText
    status: NotificationStatus
    created_at: AwareDatetime
    sent_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_delivery(self) -> "Notification":
        if self.status == NotificationStatus.SENT and self.sent_at is None:
            raise ValueError("sent notifications require sent_at")
        if self.sent_at is not None and self.sent_at < self.created_at:
            raise ValueError("sent_at cannot be earlier than created_at")
        return self

from enum import Enum

from pydantic import model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Ticket(DomainModel):
    ticket_id: Identifier
    case_id: Identifier
    subject: NonEmptyText
    description: NonEmptyText
    status: TicketStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> "Ticket":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self

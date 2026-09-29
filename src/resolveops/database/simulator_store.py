from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from resolveops.database.records import CaseRecord
from resolveops.database.simulator_records import (
    NotificationRecord,
    PolicyIssueTypeRecord,
    PolicyRecord,
    TicketRecord,
)
from resolveops.models.case import CaseIssueType
from resolveops.models.notification import Notification
from resolveops.models.policy import Policy, PolicyStatus
from resolveops.models.ticket import Ticket


class SimulatorStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_ticket(self, ticket: Ticket) -> None:
        self.session.add(
            TicketRecord(
                ticket_id=ticket.ticket_id,
                case_id=ticket.case_id,
                subject=ticket.subject,
                description=ticket.description,
                status=ticket.status,
                created_at=ticket.created_at,
                updated_at=ticket.updated_at,
            )
        )

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        record = self.session.get(TicketRecord, ticket_id)
        if record is None:
            return None
        return self._ticket_from_record(record)

    def list_tickets(self, case_id: str) -> list[Ticket]:
        statement = (
            select(TicketRecord)
            .where(TicketRecord.case_id == case_id)
            .order_by(TicketRecord.created_at, TicketRecord.ticket_id)
        )
        return [self._ticket_from_record(record) for record in self.session.scalars(statement)]

    def add_policy(self, policy: Policy) -> None:
        self.session.add(
            PolicyRecord(
                policy_id=policy.policy_id,
                title=policy.title,
                version=policy.version,
                status=policy.status,
                content=policy.content,
                source=policy.source,
                effective_at=policy.effective_at,
                expires_at=policy.expires_at,
                issue_type_links=[
                    PolicyIssueTypeRecord(
                        policy_id=policy.policy_id,
                        issue_type=issue_type,
                    )
                    for issue_type in policy.issue_types
                ],
            )
        )

    def get_policy(self, policy_id: str) -> Policy | None:
        statement = (
            select(PolicyRecord)
            .where(PolicyRecord.policy_id == policy_id)
            .options(selectinload(PolicyRecord.issue_type_links))
        )
        record = self.session.scalar(statement)
        if record is None:
            return None
        return self._policy_from_record(record)

    def list_effective_policies(
        self,
        *,
        as_of: datetime,
        issue_type: CaseIssueType | None = None,
    ) -> list[Policy]:
        statement = (
            select(PolicyRecord)
            .where(
                PolicyRecord.status == PolicyStatus.ACTIVE,
                PolicyRecord.effective_at <= as_of,
                or_(PolicyRecord.expires_at.is_(None), PolicyRecord.expires_at > as_of),
            )
            .options(selectinload(PolicyRecord.issue_type_links))
            .order_by(PolicyRecord.policy_id)
        )
        if issue_type is not None:
            statement = statement.where(
                PolicyRecord.issue_type_links.any(PolicyIssueTypeRecord.issue_type == issue_type)
            )
        return [self._policy_from_record(record) for record in self.session.scalars(statement)]

    def add_notification(self, notification: Notification) -> None:
        customer_case = self.session.get(CaseRecord, notification.case_id)
        if customer_case is None:
            raise ValueError(f"case {notification.case_id} does not exist")
        if customer_case.customer_id != notification.customer_id:
            raise ValueError("notification customer does not match the case customer")

        self.session.add(
            NotificationRecord(
                notification_id=notification.notification_id,
                case_id=notification.case_id,
                customer_id=notification.customer_id,
                channel=notification.channel,
                recipient=notification.recipient,
                message=notification.message,
                status=notification.status,
                created_at=notification.created_at,
                sent_at=notification.sent_at,
            )
        )

    def get_notification(self, notification_id: str) -> Notification | None:
        record = self.session.get(NotificationRecord, notification_id)
        if record is None:
            return None
        return self._notification_from_record(record)

    def list_notifications(self, case_id: str) -> list[Notification]:
        statement = (
            select(NotificationRecord)
            .where(NotificationRecord.case_id == case_id)
            .order_by(NotificationRecord.created_at, NotificationRecord.notification_id)
        )
        return [
            self._notification_from_record(record) for record in self.session.scalars(statement)
        ]

    @staticmethod
    def _ticket_from_record(record: TicketRecord) -> Ticket:
        return Ticket(
            ticket_id=record.ticket_id,
            case_id=record.case_id,
            subject=record.subject,
            description=record.description,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _policy_from_record(record: PolicyRecord) -> Policy:
        return Policy(
            policy_id=record.policy_id,
            title=record.title,
            version=record.version,
            status=record.status,
            issue_types=[link.issue_type for link in record.issue_type_links],
            content=record.content,
            source=record.source,
            effective_at=record.effective_at,
            expires_at=record.expires_at,
        )

    @staticmethod
    def _notification_from_record(record: NotificationRecord) -> Notification:
        return Notification(
            notification_id=record.notification_id,
            case_id=record.case_id,
            customer_id=record.customer_id,
            channel=record.channel,
            recipient=record.recipient,
            message=record.message,
            status=record.status,
            created_at=record.created_at,
            sent_at=record.sent_at,
        )

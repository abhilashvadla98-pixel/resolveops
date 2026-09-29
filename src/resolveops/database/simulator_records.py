from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.models.case import CaseIssueType
from resolveops.models.notification import NotificationChannel, NotificationStatus
from resolveops.models.policy import PolicyStatus
from resolveops.models.ticket import TicketStatus


class TicketRecord(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="ck_tickets_timestamp_order"),
    )

    ticket_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    subject: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(enum_type(TicketStatus, "ticket_status"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class PolicyRecord(Base):
    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_policies_positive_version"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at",
            name="ck_policies_effective_order",
        ),
    )

    policy_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[PolicyStatus] = mapped_column(enum_type(PolicyStatus, "policy_status"))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(1000))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    issue_type_links: Mapped[list["PolicyIssueTypeRecord"]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="PolicyIssueTypeRecord.issue_type",
    )


class PolicyIssueTypeRecord(Base):
    __tablename__ = "policy_issue_types"

    policy_id: Mapped[str] = mapped_column(
        ForeignKey("policies.policy_id", ondelete="CASCADE"),
        primary_key=True,
    )
    issue_type: Mapped[CaseIssueType] = mapped_column(
        enum_type(CaseIssueType, "policy_case_issue_type"),
        primary_key=True,
    )

    policy: Mapped[PolicyRecord] = relationship(back_populates="issue_type_links")


class NotificationRecord(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "status != 'sent' OR sent_at IS NOT NULL",
            name="ck_notifications_sent_at",
        ),
        CheckConstraint(
            "sent_at IS NULL OR sent_at >= created_at",
            name="ck_notifications_delivery_order",
        ),
    )

    notification_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_type(NotificationChannel, "notification_channel")
    )
    recipient: Mapped[str] = mapped_column(String(1000))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(
        enum_type(NotificationStatus, "notification_status")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

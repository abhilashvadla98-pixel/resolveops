from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum as PythonEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from resolveops.database.base import Base
from resolveops.models.case import (
    CaseIntakeStatus,
    CaseIssueStatus,
    CaseIssueType,
    CaseStatus,
    IssueActionStatus,
    IssueFinding,
    VerificationStatus,
)
from resolveops.models.customer import CustomerStatus, CustomerTier
from resolveops.models.order import OrderStatus
from resolveops.models.payment import PaymentStatus
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.models.returns import ReturnStatus


def enum_type(enum_class: type[PythonEnum], name: str, length: int = 32) -> Enum:
    return Enum(
        enum_class,
        name=name,
        length=length,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [item.value for item in values],
    )


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("database timestamps must include a timezone")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class CustomerRecord(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(1000))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    tier: Mapped[CustomerTier] = mapped_column(enum_type(CustomerTier, "customer_tier"))
    status: Mapped[CustomerStatus] = mapped_column(enum_type(CustomerStatus, "customer_status"))


class OrderRecord(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_orders_positive_total"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_orders_currency",
        ),
        UniqueConstraint("order_id", "customer_id", name="uq_orders_customer"),
    )

    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(enum_type(OrderStatus, "order_status"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())

    items: Mapped[list["OrderItemRecord"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItemRecord.order_item_id",
    )


class OrderItemRecord(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_positive_quantity"),
        CheckConstraint("unit_price > 0", name="ck_order_items_positive_price"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_order_items_currency",
        ),
        UniqueConstraint("order_item_id", "order_id", name="uq_order_items_order"),
    )

    order_item_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id", ondelete="CASCADE"))
    sku: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(1000))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))

    order: Mapped[OrderRecord] = relationship(back_populates="items")


class PaymentRecord(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_positive_amount"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_payments_currency",
        ),
        CheckConstraint(
            "status != 'captured' OR captured_at IS NOT NULL",
            name="ck_payments_captured_at",
        ),
        CheckConstraint(
            "captured_at IS NULL OR captured_at >= created_at",
            name="ck_payments_capture_order",
        ),
        UniqueConstraint("payment_id", "order_id", name="uq_payments_order"),
    )

    payment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[PaymentStatus] = mapped_column(enum_type(PaymentStatus, "payment_status"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReturnRecord(Base):
    __tablename__ = "returns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "customer_id"],
            ["orders.order_id", "orders.customer_id"],
            name="fk_returns_order_customer",
        ),
        CheckConstraint(
            "status NOT IN ('received', 'completed') OR received_at IS NOT NULL",
            name="ck_returns_received_at",
        ),
        CheckConstraint(
            "received_at IS NULL OR received_at >= created_at",
            name="ck_returns_received_order",
        ),
        UniqueConstraint("return_id", "order_id", name="uq_returns_order"),
    )

    return_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    customer_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[ReturnStatus] = mapped_column(enum_type(ReturnStatus, "return_status"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    items: Mapped[list["ReturnItemRecord"]] = relationship(
        back_populates="customer_return",
        cascade="all, delete-orphan",
        order_by="ReturnItemRecord.order_item_id",
    )
    refunds: Mapped[list["RefundRecord"]] = relationship(
        back_populates="customer_return",
        order_by="RefundRecord.refund_id",
    )


class ReturnItemRecord(Base):
    __tablename__ = "return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_return_items_positive_quantity"),
        ForeignKeyConstraint(
            ["return_id", "order_id"],
            ["returns.return_id", "returns.order_id"],
            ondelete="CASCADE",
            name="fk_return_items_return_order",
        ),
        ForeignKeyConstraint(
            ["order_item_id", "order_id"],
            ["order_items.order_item_id", "order_items.order_id"],
            name="fk_return_items_order_item",
        ),
    )

    return_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_item_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(1000))

    customer_return: Mapped[ReturnRecord] = relationship(back_populates="items")


class CaseRecord(Base):
    __tablename__ = "cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "customer_id"],
            ["orders.order_id", "orders.customer_id"],
            name="fk_cases_order_customer",
        ),
        CheckConstraint("updated_at >= opened_at", name="ck_cases_timestamp_order"),
        UniqueConstraint("case_id", "order_id", name="uq_cases_order"),
        Index("ix_cases_updated_at_desc", "updated_at"),
    )

    case_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(100), index=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[CaseStatus] = mapped_column(enum_type(CaseStatus, "case_status"))
    complaint_text: Mapped[str | None] = mapped_column(Text)
    intake_status: Mapped[CaseIntakeStatus | None] = mapped_column(
        enum_type(CaseIntakeStatus, "case_intake_status")
    )
    intake_summary: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())

    issues: Mapped[list["CaseIssueRecord"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="CaseIssueRecord.issue_id",
    )


class CaseIssueRecord(Base):
    __tablename__ = "case_issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "order_id"],
            ["cases.case_id", "cases.order_id"],
            ondelete="CASCADE",
            name="fk_case_issues_case_order",
        ),
        ForeignKeyConstraint(
            ["return_id", "order_id"],
            ["returns.return_id", "returns.order_id"],
            name="fk_case_issues_return_order",
        ),
        CheckConstraint(
            "issue_type != 'duplicate_charge' OR return_id IS NULL",
            name="ck_case_issues_duplicate_return",
        ),
        UniqueConstraint("issue_id", "order_id", name="uq_case_issues_order"),
    )

    issue_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(100))
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    issue_type: Mapped[CaseIssueType] = mapped_column(enum_type(CaseIssueType, "case_issue_type"))
    status: Mapped[CaseIssueStatus] = mapped_column(enum_type(CaseIssueStatus, "case_issue_status"))
    finding: Mapped[IssueFinding] = mapped_column(enum_type(IssueFinding, "issue_finding"))
    return_id: Mapped[str | None] = mapped_column(String(100))
    reported_at: Mapped[datetime] = mapped_column(UTCDateTime())
    classification_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))

    case: Mapped[CaseRecord] = relationship(back_populates="issues")
    payment_links: Mapped[list["CaseIssuePaymentRecord"]] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="CaseIssuePaymentRecord.payment_id",
    )
    evidence: Mapped[list["CaseIssueEvidenceRecord"]] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="CaseIssueEvidenceRecord.evidence_id",
    )
    actions: Mapped[list["CaseIssueActionRecord"]] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="CaseIssueActionRecord.action_id",
    )
    verification: Mapped["CaseIssueVerificationRecord | None"] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        uselist=False,
    )
    resolution: Mapped["CaseIssueResolutionRecord | None"] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        uselist=False,
    )


class CaseIssuePaymentRecord(Base):
    __tablename__ = "case_issue_payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["issue_id", "order_id"],
            ["case_issues.issue_id", "case_issues.order_id"],
            ondelete="CASCADE",
            name="fk_case_issue_payments_issue_order",
        ),
        ForeignKeyConstraint(
            ["payment_id", "order_id"],
            ["payments.payment_id", "payments.order_id"],
            name="fk_case_issue_payments_payment_order",
        ),
    )

    issue_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100))

    issue: Mapped[CaseIssueRecord] = relationship(back_populates="payment_links")


class CaseIssueEvidenceRecord(Base):
    __tablename__ = "case_issue_evidence"

    evidence_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    issue_id: Mapped[str] = mapped_column(
        ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
        index=True,
    )
    source: Mapped[str] = mapped_column(String(1000))
    reference_id: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime())

    issue: Mapped[CaseIssueRecord] = relationship(back_populates="evidence")


class CaseIssueActionRecord(Base):
    __tablename__ = "case_issue_actions"

    action_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    issue_id: Mapped[str] = mapped_column(
        ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(1000))
    status: Mapped[IssueActionStatus] = mapped_column(
        enum_type(IssueActionStatus, "issue_action_status")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    issue: Mapped[CaseIssueRecord] = relationship(back_populates="actions")


class CaseIssueVerificationRecord(Base):
    __tablename__ = "case_issue_verifications"

    issue_id: Mapped[str] = mapped_column(
        ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[VerificationStatus] = mapped_column(
        enum_type(VerificationStatus, "verification_status")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    issue: Mapped[CaseIssueRecord] = relationship(back_populates="verification")


class CaseIssueResolutionRecord(Base):
    __tablename__ = "case_issue_resolutions"

    issue_id: Mapped[str] = mapped_column(
        ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
        primary_key=True,
    )
    summary: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime] = mapped_column(UTCDateTime())

    issue: Mapped[CaseIssueRecord] = relationship(back_populates="resolution")


class RefundRecord(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_refunds_positive_amount"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_refunds_currency",
        ),
        CheckConstraint(
            "(kind != 'return' OR return_id IS NOT NULL) "
            "AND (kind != 'duplicate_charge' OR return_id IS NULL)",
            name="ck_refunds_kind_context",
        ),
        CheckConstraint(
            "status != 'completed' OR completed_at IS NOT NULL",
            name="ck_refunds_completed_at",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_refunds_completion_order",
        ),
        ForeignKeyConstraint(
            ["payment_id", "order_id"],
            ["payments.payment_id", "payments.order_id"],
            name="fk_refunds_payment_order",
        ),
        ForeignKeyConstraint(
            ["issue_id", "order_id"],
            ["case_issues.issue_id", "case_issues.order_id"],
            name="fk_refunds_issue_order",
        ),
        ForeignKeyConstraint(
            ["return_id", "order_id"],
            ["returns.return_id", "returns.order_id"],
            name="fk_refunds_return_order",
        ),
    )

    refund_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(100), index=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    issue_id: Mapped[str] = mapped_column(String(100), index=True)
    return_id: Mapped[str | None] = mapped_column(String(100), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[RefundStatus] = mapped_column(enum_type(RefundStatus, "refund_status"))
    kind: Mapped[RefundKind] = mapped_column(enum_type(RefundKind, "refund_kind"))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    customer_return: Mapped[ReturnRecord | None] = relationship(back_populates="refunds")

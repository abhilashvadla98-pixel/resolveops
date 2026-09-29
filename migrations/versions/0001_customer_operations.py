"""Create the customer operations schema.

Revision ID: 0001_customer_operations
Revises:
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_customer_operations"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def text_enum(*values: str, name: str, length: int = 32) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        length=length,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.String(length=100), primary_key=True),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column(
            "tier",
            text_enum("standard", "gold", "enterprise", name="customer_tier"),
            nullable=False,
        ),
        sa.Column(
            "status",
            text_enum("active", "suspended", "closed", name="customer_status"),
            nullable=False,
        ),
    )

    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "customer_id",
            sa.String(length=100),
            sa.ForeignKey("customers.customer_id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            text_enum(
                "created",
                "paid",
                "shipped",
                "delivered",
                "partially_returned",
                "returned",
                "cancelled",
                name="order_status",
            ),
            nullable=False,
        ),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_amount > 0", name="ck_orders_positive_total"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_orders_currency",
        ),
        sa.UniqueConstraint("order_id", "customer_id", name="uq_orders_customer"),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])

    op.create_table(
        "order_items",
        sa.Column("order_item_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(length=100),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_positive_quantity"),
        sa.CheckConstraint("unit_price > 0", name="ck_order_items_positive_price"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_order_items_currency",
        ),
        sa.UniqueConstraint("order_item_id", "order_id", name="uq_order_items_order"),
    )

    op.create_table(
        "payments",
        sa.Column("payment_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(length=100),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "pending",
                "authorized",
                "captured",
                "failed",
                "voided",
                name="payment_status",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_payments_positive_amount"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_payments_currency",
        ),
        sa.CheckConstraint(
            "status != 'captured' OR captured_at IS NOT NULL",
            name="ck_payments_captured_at",
        ),
        sa.CheckConstraint(
            "captured_at IS NULL OR captured_at >= created_at",
            name="ck_payments_capture_order",
        ),
        sa.UniqueConstraint("payment_id", "order_id", name="uq_payments_order"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])

    op.create_table(
        "returns",
        sa.Column("return_id", sa.String(length=100), primary_key=True),
        sa.Column("order_id", sa.String(length=100), nullable=False),
        sa.Column("customer_id", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "requested",
                "authorized",
                "in_transit",
                "received",
                "completed",
                "rejected",
                "cancelled",
                name="return_status",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["order_id", "customer_id"],
            ["orders.order_id", "orders.customer_id"],
            name="fk_returns_order_customer",
        ),
        sa.CheckConstraint(
            "status NOT IN ('received', 'completed') OR received_at IS NOT NULL",
            name="ck_returns_received_at",
        ),
        sa.CheckConstraint(
            "received_at IS NULL OR received_at >= created_at",
            name="ck_returns_received_order",
        ),
        sa.UniqueConstraint("return_id", "order_id", name="uq_returns_order"),
    )
    op.create_index("ix_returns_order_id", "returns", ["order_id"])
    op.create_index("ix_returns_customer_id", "returns", ["customer_id"])

    op.create_table(
        "return_items",
        sa.Column("return_id", sa.String(length=100), primary_key=True),
        sa.Column("order_item_id", sa.String(length=100), primary_key=True),
        sa.Column("order_id", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_return_items_positive_quantity"),
        sa.ForeignKeyConstraint(
            ["return_id", "order_id"],
            ["returns.return_id", "returns.order_id"],
            ondelete="CASCADE",
            name="fk_return_items_return_order",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id", "order_id"],
            ["order_items.order_item_id", "order_items.order_id"],
            name="fk_return_items_order_item",
        ),
    )

    op.create_table(
        "cases",
        sa.Column("case_id", sa.String(length=100), primary_key=True),
        sa.Column("customer_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "open",
                "in_progress",
                "pending_approval",
                "resolved",
                "escalated",
                "closed",
                name="case_status",
            ),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id", "customer_id"],
            ["orders.order_id", "orders.customer_id"],
            name="fk_cases_order_customer",
        ),
        sa.CheckConstraint("updated_at >= opened_at", name="ck_cases_timestamp_order"),
        sa.UniqueConstraint("case_id", "order_id", name="uq_cases_order"),
    )
    op.create_index("ix_cases_customer_id", "cases", ["customer_id"])
    op.create_index("ix_cases_order_id", "cases", ["order_id"])

    op.create_table(
        "case_issues",
        sa.Column("issue_id", sa.String(length=100), primary_key=True),
        sa.Column("case_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), nullable=False),
        sa.Column(
            "issue_type",
            text_enum(
                "duplicate_charge",
                "missing_return_refund",
                name="case_issue_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            text_enum(
                "reported",
                "investigating",
                "policy_review",
                "action_pending",
                "action_executed",
                "verifying",
                "resolved",
                "escalated",
                name="case_issue_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "finding",
            text_enum(
                "undetermined",
                "confirmed",
                "rejected",
                name="issue_finding",
            ),
            nullable=False,
        ),
        sa.Column("return_id", sa.String(length=100), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id", "order_id"],
            ["cases.case_id", "cases.order_id"],
            ondelete="CASCADE",
            name="fk_case_issues_case_order",
        ),
        sa.ForeignKeyConstraint(
            ["return_id", "order_id"],
            ["returns.return_id", "returns.order_id"],
            name="fk_case_issues_return_order",
        ),
        sa.CheckConstraint(
            "issue_type != 'duplicate_charge' OR return_id IS NULL",
            name="ck_case_issues_duplicate_return",
        ),
        sa.UniqueConstraint("issue_id", "order_id", name="uq_case_issues_order"),
    )
    op.create_index("ix_case_issues_order_id", "case_issues", ["order_id"])

    op.create_table(
        "case_issue_payments",
        sa.Column("issue_id", sa.String(length=100), primary_key=True),
        sa.Column("payment_id", sa.String(length=100), primary_key=True),
        sa.Column("order_id", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["issue_id", "order_id"],
            ["case_issues.issue_id", "case_issues.order_id"],
            ondelete="CASCADE",
            name="fk_case_issue_payments_issue_order",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id", "order_id"],
            ["payments.payment_id", "payments.order_id"],
            name="fk_case_issue_payments_payment_order",
        ),
    )

    op.create_table(
        "case_issue_evidence",
        sa.Column("evidence_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "issue_id",
            sa.String(length=100),
            sa.ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("reference_id", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_case_issue_evidence_issue_id", "case_issue_evidence", ["issue_id"])

    op.create_table(
        "case_issue_actions",
        sa.Column("action_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "issue_id",
            sa.String(length=100),
            sa.ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "proposed",
                "authorized",
                "executed",
                "failed",
                name="issue_action_status",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_case_issue_actions_issue_id", "case_issue_actions", ["issue_id"])

    op.create_table(
        "case_issue_verifications",
        sa.Column(
            "issue_id",
            sa.String(length=100),
            sa.ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "status",
            text_enum("pending", "passed", "failed", name="verification_status"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "case_issue_resolutions",
        sa.Column(
            "issue_id",
            sa.String(length=100),
            sa.ForeignKey("case_issues.issue_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "refunds",
        sa.Column("refund_id", sa.String(length=100), primary_key=True),
        sa.Column("payment_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), nullable=False),
        sa.Column("issue_id", sa.String(length=100), nullable=False),
        sa.Column("return_id", sa.String(length=100), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "pending",
                "processing",
                "completed",
                "failed",
                "cancelled",
                name="refund_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "kind",
            text_enum(
                "duplicate_charge",
                "return",
                "goodwill",
                "other",
                name="refund_kind",
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_refunds_positive_amount"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_refunds_currency",
        ),
        sa.CheckConstraint(
            "(kind != 'return' OR return_id IS NOT NULL) "
            "AND (kind != 'duplicate_charge' OR return_id IS NULL)",
            name="ck_refunds_kind_context",
        ),
        sa.CheckConstraint(
            "status != 'completed' OR completed_at IS NOT NULL",
            name="ck_refunds_completed_at",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_refunds_completion_order",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id", "order_id"],
            ["payments.payment_id", "payments.order_id"],
            name="fk_refunds_payment_order",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id", "order_id"],
            ["case_issues.issue_id", "case_issues.order_id"],
            name="fk_refunds_issue_order",
        ),
        sa.ForeignKeyConstraint(
            ["return_id", "order_id"],
            ["returns.return_id", "returns.order_id"],
            name="fk_refunds_return_order",
        ),
    )
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_index("ix_refunds_issue_id", "refunds", ["issue_id"])
    op.create_index("ix_refunds_return_id", "refunds", ["return_id"])


def downgrade() -> None:
    op.drop_index("ix_refunds_return_id", table_name="refunds")
    op.drop_index("ix_refunds_issue_id", table_name="refunds")
    op.drop_index("ix_refunds_order_id", table_name="refunds")
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_table("refunds")
    op.drop_table("case_issue_resolutions")
    op.drop_table("case_issue_verifications")
    op.drop_index("ix_case_issue_actions_issue_id", table_name="case_issue_actions")
    op.drop_table("case_issue_actions")
    op.drop_index("ix_case_issue_evidence_issue_id", table_name="case_issue_evidence")
    op.drop_table("case_issue_evidence")
    op.drop_table("case_issue_payments")
    op.drop_index("ix_case_issues_order_id", table_name="case_issues")
    op.drop_table("case_issues")
    op.drop_index("ix_cases_order_id", table_name="cases")
    op.drop_index("ix_cases_customer_id", table_name="cases")
    op.drop_table("cases")
    op.drop_table("return_items")
    op.drop_index("ix_returns_customer_id", table_name="returns")
    op.drop_index("ix_returns_order_id", table_name="returns")
    op.drop_table("returns")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
    op.drop_table("order_items")
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_table("orders")
    op.drop_table("customers")

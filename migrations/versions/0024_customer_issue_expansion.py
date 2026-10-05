"""Add incorrect-refund and cancelled-order customer issue types."""

import sqlalchemy as sa
from alembic import op

revision = "0024_customer_issue_expansion"
down_revision = "0023_refund_lifecycle_states"
branch_labels = None
depends_on = None

OLD_ISSUE_TYPES = ("duplicate_charge", "missing_return_refund", "repository_access")
NEW_ISSUE_TYPES = (
    "duplicate_charge",
    "missing_return_refund",
    "incorrect_refund_amount",
    "cancelled_order_charge",
    "repository_access",
)
OLD_REFUND_KINDS = ("duplicate_charge", "return", "goodwill", "other")
NEW_REFUND_KINDS = (*OLD_REFUND_KINDS[:2], "cancelled_order", *OLD_REFUND_KINDS[2:])


def enum(name: str, values: tuple[str, ...], *, length: int = 32) -> sa.Enum:
    return sa.Enum(*values, name=name, length=length, native_enum=False, create_constraint=True)


def change(*, upgrading: bool) -> None:
    before, after = (0, 1) if upgrading else (1, 0)
    issue_sets = (OLD_ISSUE_TYPES, NEW_ISSUE_TYPES)
    for table, constraint in (
        ("case_issues", "case_issue_type"),
        ("policy_issue_types", "policy_case_issue_type"),
        ("knowledge_document_issue_types", "knowledge_case_issue_type"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "issue_type",
                existing_type=enum(constraint, issue_sets[before]),
                type_=enum(constraint, issue_sets[after]),
                existing_nullable=False,
            )
    refund_sets = (OLD_REFUND_KINDS, NEW_REFUND_KINDS)
    with op.batch_alter_table("refunds") as batch:
        batch.alter_column(
            "kind",
            existing_type=enum("refund_kind", refund_sets[before]),
            type_=enum("refund_kind", refund_sets[after]),
            existing_nullable=False,
        )
        batch.drop_constraint("ck_refunds_kind_context", type_="check")
        context_rule = (
            "(kind != 'return' OR return_id IS NOT NULL) "
            "AND (kind NOT IN ('duplicate_charge', 'cancelled_order') OR return_id IS NULL)"
            if upgrading
            else "(kind != 'return' OR return_id IS NOT NULL) "
            "AND (kind != 'duplicate_charge' OR return_id IS NULL)"
        )
        batch.create_check_constraint("ck_refunds_kind_context", context_rule)


def upgrade() -> None:
    change(upgrading=True)


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "case_issues",
        "policy_issue_types",
        "knowledge_document_issue_types",
    ):
        connection.execute(
            sa.text(
                f"UPDATE {table} SET issue_type = 'missing_return_refund' "
                "WHERE issue_type = 'incorrect_refund_amount'"
            )
        )
        connection.execute(
            sa.text(
                f"UPDATE {table} SET issue_type = 'duplicate_charge' "
                "WHERE issue_type = 'cancelled_order_charge'"
            )
        )
    connection.execute(sa.text("UPDATE refunds SET kind = 'other' WHERE kind = 'cancelled_order'"))
    change(upgrading=False)

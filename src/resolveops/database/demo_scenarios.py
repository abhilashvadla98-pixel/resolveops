from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from resolveops.database.action_records import (
    AuditEventRecord,
    OperationRecord,
    ReliabilityEventRecord,
)
from resolveops.database.demo_records import DemoScenarioRecord
from resolveops.database.records import (
    CaseIssueActionRecord,
    CaseIssueEvidenceRecord,
    CaseIssuePaymentRecord,
    CaseIssueRecord,
    CaseIssueResolutionRecord,
    CaseIssueVerificationRecord,
    CaseRecord,
    CustomerRecord,
    OrderItemRecord,
    OrderRecord,
    PaymentRecord,
    RefundRecord,
    ReturnItemRecord,
    ReturnRecord,
)
from resolveops.database.seed import (
    seed_additional_it_cases,
    seed_customer_operations,
    seed_simulator_resources,
)
from resolveops.database.simulator_records import NotificationRecord, TicketRecord
from resolveops.database.store import CustomerOperationsStore
from resolveops.database.workflow_records import (
    WorkflowApprovalRecord,
    WorkflowEventRecord,
    WorkflowRunRecord,
)
from resolveops.models.case import (
    Case,
    CaseIntakeStatus,
    CaseIssue,
    CaseIssueAction,
    CaseIssueStatus,
    CaseIssueType,
    CaseIssueVerification,
    CaseStatus,
    IssueActionStatus,
    IssueFinding,
    VerificationStatus,
)
from resolveops.models.customer import Customer, CustomerStatus, CustomerTier
from resolveops.models.order import Order, OrderItem, OrderStatus
from resolveops.models.payment import Payment, PaymentStatus
from resolveops.models.refund import Refund, RefundKind, RefundStatus
from resolveops.models.returns import Return, ReturnItem, ReturnStatus

SCENARIO_ROWS = (
    (
        "A",
        "Duplicate payment before delivery",
        "customer",
        "CASE-DEMO-A",
        "Two captured payments exist while the order is not delivered.",
    ),
    (
        "B",
        "Missing return refund",
        "customer",
        "CASE-DEMO-B",
        "A received return has no completed refund.",
    ),
    (
        "C",
        "Two issues in one complaint",
        "customer",
        "CASE-1001",
        "Duplicate payment and missing return refund remain independent issues.",
    ),
    (
        "D",
        "Approval-required refund",
        "customer",
        "CASE-DEMO-D",
        "A confirmed refund exceeds the operator limit and must pause.",
    ),
    (
        "E",
        "Insufficient evidence",
        "customer",
        "CASE-DEMO-E",
        "The available records do not prove a duplicate capture.",
    ),
    (
        "F",
        "Existing external refund",
        "customer",
        "CASE-DEMO-F",
        "A refund already exists, so another side effect is forbidden.",
    ),
    (
        "G",
        "Repository access request",
        "employee_it",
        "ITCASE-2001",
        "Identity, manager approval, access, ticket, and notification evidence.",
    ),
    (
        "H",
        "Verification recovery",
        "customer",
        "CASE-DEMO-H",
        "Execution exists while independent verification requires recovery.",
    ),
)


def seed_demo_scenarios(session: Session) -> bool:
    created = False
    definitions = (
        (
            "A",
            CaseIssueType.DUPLICATE_CHARGE,
            CaseIssueStatus.INVESTIGATING,
            IssueFinding.UNDETERMINED,
            False,
            False,
        ),
        (
            "B",
            CaseIssueType.MISSING_RETURN_REFUND,
            CaseIssueStatus.INVESTIGATING,
            IssueFinding.UNDETERMINED,
            True,
            False,
        ),
        (
            "D",
            CaseIssueType.DUPLICATE_CHARGE,
            CaseIssueStatus.ACTION_PENDING,
            IssueFinding.CONFIRMED,
            False,
            False,
        ),
        (
            "E",
            CaseIssueType.DUPLICATE_CHARGE,
            CaseIssueStatus.ESCALATED,
            IssueFinding.UNDETERMINED,
            False,
            False,
        ),
        (
            "F",
            CaseIssueType.DUPLICATE_CHARGE,
            CaseIssueStatus.ACTION_PENDING,
            IssueFinding.CONFIRMED,
            False,
            True,
        ),
        (
            "H",
            CaseIssueType.DUPLICATE_CHARGE,
            CaseIssueStatus.VERIFYING,
            IssueFinding.CONFIRMED,
            False,
            True,
        ),
    )
    for scenario_id, issue_type, issue_status, finding, with_return, with_refund in definitions:
        if session.get(CustomerRecord, f"CUST-DEMO-{scenario_id}") is None:
            _seed_customer_scenario(
                session,
                scenario_id=scenario_id,
                issue_type=issue_type,
                issue_status=issue_status,
                finding=finding,
                with_return=with_return,
                with_refund=with_refund,
            )
            created = True
    for scenario_id, title, domain, case_id, description in SCENARIO_ROWS:
        if session.get(DemoScenarioRecord, scenario_id) is None:
            session.add(
                DemoScenarioRecord(
                    scenario_id=scenario_id,
                    title=title,
                    domain=domain,
                    case_id=case_id,
                    description=description,
                )
            )
            created = True
    session.flush()
    return created


def list_demo_scenarios(session: Session) -> list[DemoScenarioRecord]:
    return list(
        session.scalars(select(DemoScenarioRecord).order_by(DemoScenarioRecord.scenario_id))
    )


def reset_demo_scenarios(session: Session) -> None:
    reset_order = (
        DemoScenarioRecord,
        WorkflowApprovalRecord,
        WorkflowEventRecord,
        WorkflowRunRecord,
        AuditEventRecord,
        ReliabilityEventRecord,
        OperationRecord,
        NotificationRecord,
        TicketRecord,
        RefundRecord,
        CaseIssueResolutionRecord,
        CaseIssueVerificationRecord,
        CaseIssueActionRecord,
        CaseIssueEvidenceRecord,
        CaseIssuePaymentRecord,
        CaseIssueRecord,
        CaseRecord,
        ReturnItemRecord,
        ReturnRecord,
        PaymentRecord,
        OrderItemRecord,
        OrderRecord,
        CustomerRecord,
    )
    for record in reset_order:
        session.execute(delete(record))
    session.flush()
    seed_customer_operations(session)
    seed_simulator_resources(session)
    seed_additional_it_cases(session)
    seed_demo_scenarios(session)


def _seed_customer_scenario(
    session: Session,
    *,
    scenario_id: str,
    issue_type: CaseIssueType,
    issue_status: CaseIssueStatus,
    finding: IssueFinding,
    with_return: bool,
    with_refund: bool,
) -> None:
    store = CustomerOperationsStore(session)
    base = datetime(2026, 9, 21, 13, 0, tzinfo=UTC) + timedelta(hours=ord(scenario_id) - 65)
    customer_id = f"CUST-DEMO-{scenario_id}"
    order_id = f"ORD-DEMO-{scenario_id}"
    case_id = f"CASE-DEMO-{scenario_id}"
    issue_id = f"ISSUE-DEMO-{scenario_id}"
    amount = Decimal("650.00") if scenario_id == "D" else Decimal("120.00")
    store.add_customer(
        Customer(
            customer_id=customer_id,
            name=f"Demo Customer {scenario_id}",
            email=f"demo.{scenario_id.lower()}@example.com",
            tier=CustomerTier.STANDARD,
            status=CustomerStatus.ACTIVE,
        )
    )
    store.add_order(
        Order(
            order_id=order_id,
            customer_id=customer_id,
            status=OrderStatus.PAID if scenario_id == "A" else OrderStatus.DELIVERED,
            total_amount=amount,
            currency="USD",
            items=[
                OrderItem(
                    order_item_id=f"ITEM-DEMO-{scenario_id}",
                    order_id=order_id,
                    sku=f"SKU-DEMO-{scenario_id}",
                    name="Wireless headphones",
                    quantity=1,
                    unit_price=amount,
                    currency="USD",
                )
            ],
            created_at=base,
        )
    )
    session.flush()
    first_status = PaymentStatus.AUTHORIZED if scenario_id == "E" else PaymentStatus.CAPTURED
    store.add_payment(
        Payment(
            payment_id=f"PAY-DEMO-{scenario_id}-1",
            order_id=order_id,
            amount=amount,
            currency="USD",
            status=first_status,
            created_at=base,
            captured_at=base + timedelta(minutes=1)
            if first_status == PaymentStatus.CAPTURED
            else None,
        )
    )
    if issue_type == CaseIssueType.DUPLICATE_CHARGE:
        store.add_payment(
            Payment(
                payment_id=f"PAY-DEMO-{scenario_id}-2",
                order_id=order_id,
                amount=amount,
                currency="USD",
                status=PaymentStatus.CAPTURED,
                created_at=base + timedelta(minutes=2),
                captured_at=base + timedelta(minutes=3),
            )
        )
    return_id = None
    if with_return:
        return_id = f"RET-DEMO-{scenario_id}"
        store.add_return(
            Return(
                return_id=return_id,
                order_id=order_id,
                customer_id=customer_id,
                status=ReturnStatus.RECEIVED,
                items=[
                    ReturnItem(
                        order_item_id=f"ITEM-DEMO-{scenario_id}", quantity=1, reason="Item returned"
                    )
                ],
                created_at=base + timedelta(days=2),
                received_at=base + timedelta(days=5),
            )
        )
    session.flush()
    actions = []
    verification = None
    if scenario_id == "H":
        actions = [
            CaseIssueAction(
                action_id="ACTION-DEMO-H",
                name="Issue duplicate-charge refund",
                status=IssueActionStatus.EXECUTED,
                created_at=base + timedelta(days=7),
                completed_at=base + timedelta(days=7, minutes=1),
            )
        ]
        verification = CaseIssueVerification(
            status=VerificationStatus.FAILED,
            summary="Refund provider read timed out; do not repeat execution.",
            checked_at=base + timedelta(days=7, minutes=2),
        )
    complaint = _complaint_for(scenario_id)
    issue = CaseIssue(
        issue_id=issue_id,
        case_id=case_id,
        order_id=order_id,
        issue_type=issue_type,
        status=issue_status,
        finding=finding,
        payment_ids=[f"PAY-DEMO-{scenario_id}-1", f"PAY-DEMO-{scenario_id}-2"]
        if issue_type == CaseIssueType.DUPLICATE_CHARGE
        else [],
        return_id=return_id,
        actions=actions,
        verification=verification,
        reported_at=base + timedelta(days=7),
        classification_confidence=0.97,
    )
    store.add_case(
        Case(
            case_id=case_id,
            customer_id=customer_id,
            order_id=order_id,
            status=CaseStatus.ESCALATED if scenario_id == "E" else CaseStatus.IN_PROGRESS,
            issues=[issue],
            complaint_text=complaint,
            intake_status=CaseIntakeStatus.CLASSIFIED,
            intake_summary="Detected a supported issue from the demo complaint.",
            opened_at=base + timedelta(days=7),
            updated_at=base + timedelta(days=7, minutes=2)
            if scenario_id == "H"
            else base + timedelta(days=7),
        )
    )
    session.flush()
    if with_refund:
        store.add_refund(
            Refund(
                refund_id=f"REF-DEMO-{scenario_id}",
                payment_id=f"PAY-DEMO-{scenario_id}-2",
                order_id=order_id,
                issue_id=issue_id,
                amount=amount,
                currency="USD",
                status=RefundStatus.PROCESSING,
                kind=RefundKind.DUPLICATE_CHARGE,
                reason="Existing controlled refund",
                created_at=base + timedelta(days=7, minutes=1),
            )
        )


def _complaint_for(scenario_id: str) -> str:
    return {
        "A": "I placed my order recently and see two completed charges before delivery.",
        "B": "I returned my headphones last week and still have not received my refund.",
        "D": "I was charged twice for my order and need the extra charge reviewed.",
        "E": "I see a payment authorization and another charge. I am not sure whether both completed.",
        "F": "I was charged twice, but support told me a refund may already be processing.",
        "H": "My duplicate-charge refund was submitted, but its verification has not finished.",
    }[scenario_id]

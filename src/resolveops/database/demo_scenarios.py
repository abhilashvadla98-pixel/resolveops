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
from resolveops.database.employee_it_records import (
    DirectoryGroupMembershipRecord,
    DirectoryGroupRecord,
    EmployeeRecord,
    EmployeeTeamMembershipRecord,
    EnterpriseIdentityRecord,
    GitAccountRecord,
    GitRepositoryAccessRecord,
    GitRepositoryRecord,
    ITAccessApprovalDecisionRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITNotificationRecord,
    ITTicketRecord,
    ITWorkflowExecutionRecord,
    TeamRecord,
)
from resolveops.database.event_records import InboundEventRecord, ResourceEventCursorRecord
from resolveops.database.feedback_records import OperatorFeedbackRecord
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
    seed_employee_it,
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
        "Pre-delivery duplicate capture",
        "customer",
        "CASE-DEMO-A",
        "Two card captures exist for an order that has not shipped.",
    ),
    (
        "B",
        "Returned item, refund absent",
        "customer",
        "CASE-DEMO-B",
        "The warehouse received the return, but no refund exists.",
    ),
    (
        "C",
        "Combined billing and return complaint",
        "customer",
        "CASE-1001",
        "One complaint contains two issues that require separate evidence and actions.",
    ),
    (
        "D",
        "High-value refund approval",
        "customer",
        "CASE-DEMO-D",
        "A confirmed duplicate charge exceeds the operator's refund authority.",
    ),
    (
        "E",
        "Authorization mistaken for a charge",
        "customer",
        "CASE-DEMO-E",
        "The second card entry is only an authorization, so the workflow must stop safely.",
    ),
    (
        "F",
        "Refund already in progress",
        "customer",
        "CASE-DEMO-F",
        "A provider refund already exists, so another refund must not be created.",
    ),
    (
        "G",
        "Approved repository access",
        "employee_it",
        "ITCASE-2001",
        "An employee request exercises identity, approval, directory and repository controls.",
    ),
    (
        "H",
        "Post-action verification recovery",
        "customer",
        "CASE-DEMO-H",
        "The refund was submitted, but its independent status check timed out.",
    ),
)


SCENARIO_CUSTOMERS = {
    "A": ("Taylor Bennett", "taylor.bennett@example.com", "Noise-cancelling headphones"),
    "B": ("Sofia Martinez", "sofia.martinez@example.com", "Wireless headphones"),
    "D": ("Aaron Blake", "aaron.blake@example.com", "Home theater receiver"),
    "E": ("Nina Shah", "nina.shah@example.com", "Mechanical keyboard"),
    "F": ("Marcus Thompson", "marcus.thompson@example.com", "Ultrawide monitor"),
    "H": ("Grace Kim", "grace.kim@example.com", "Smart speaker pair"),
}


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
        OperatorFeedbackRecord,
        WorkflowApprovalRecord,
        WorkflowEventRecord,
        WorkflowRunRecord,
        AuditEventRecord,
        ReliabilityEventRecord,
        OperationRecord,
        ResourceEventCursorRecord,
        InboundEventRecord,
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
        ITAccessApprovalDecisionRecord,
        ITWorkflowExecutionRecord,
        ITNotificationRecord,
        ITTicketRecord,
        GitRepositoryAccessRecord,
        DirectoryGroupMembershipRecord,
        ITAccessRequestRecord,
        ITAccessCaseRecord,
        GitAccountRecord,
        EnterpriseIdentityRecord,
        EmployeeTeamMembershipRecord,
        GitRepositoryRecord,
        DirectoryGroupRecord,
        TeamRecord,
        EmployeeRecord,
    )
    for record in reset_order:
        session.execute(delete(record))
    session.flush()
    seed_customer_operations(session)
    seed_simulator_resources(session)
    seed_employee_it(session)
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
    customer_name, customer_email, product_name = SCENARIO_CUSTOMERS[scenario_id]
    store.add_customer(
        Customer(
            customer_id=customer_id,
            name=customer_name,
            email=customer_email,
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
                    name=product_name,
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
            obligation_id=f"OBL-{order_id}",
            obligation_amount=amount,
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
                obligation_id=f"OBL-{order_id}",
                obligation_amount=amount,
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
            intake_summary="Complaint classified for evidence-led investigation.",
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
        "A": (
            "My card shows two completed charges for this order, but the delivery has not even "
            "shipped. Please check whether I was billed twice."
        ),
        "B": (
            "Tracking says you received my return five days ago. I still cannot see the refund "
            "on my card, and I would like an update."
        ),
        "D": (
            "The same purchase appears twice on my statement. Both entries have posted, so please "
            "review the extra charge."
        ),
        "E": (
            "I see one completed charge and another pending card entry for the same order. Can you "
            "confirm whether I was actually charged twice?"
        ),
        "F": (
            "Support confirmed the duplicate payment yesterday and said a refund was started. I "
            "want to make sure a second refund request is not opened."
        ),
        "H": (
            "I was told the duplicate charge was refunded, but nobody could confirm its current "
            "status. Please verify the existing refund instead of submitting another one."
        ),
    }[scenario_id]

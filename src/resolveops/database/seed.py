from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from resolveops.config import get_settings
from resolveops.database.employee_it_records import (
    DirectoryGroupMembershipRecord,
    DirectoryGroupRecord,
    EmployeeRecord,
    EmployeeTeamMembershipRecord,
    EnterpriseIdentityRecord,
    GitAccountRecord,
    GitRepositoryAccessRecord,
    GitRepositoryRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITNotificationRecord,
    ITTicketRecord,
    TeamRecord,
)
from resolveops.database.session import create_database_engine, create_session_factory
from resolveops.database.simulator_store import SimulatorStore
from resolveops.database.store import CustomerOperationsStore
from resolveops.employee_it.models import (
    AccessRequestStatus,
    EmploymentStatus,
    GitAccountStatus,
    IdentityStatus,
    ITCaseStatus,
    ITNotificationStatus,
    ITTicketStatus,
    MembershipStatus,
    RepositoryAccessLevel,
)
from resolveops.models.case import (
    Case,
    CaseIssue,
    CaseIssueEvidence,
    CaseIssueStatus,
    CaseIssueType,
    CaseStatus,
)
from resolveops.models.customer import Customer, CustomerStatus, CustomerTier
from resolveops.models.notification import Notification, NotificationChannel, NotificationStatus
from resolveops.models.order import Order, OrderItem, OrderStatus
from resolveops.models.payment import Payment, PaymentStatus
from resolveops.models.policy import Policy, PolicyStatus
from resolveops.models.refund import Refund, RefundKind, RefundStatus
from resolveops.models.returns import Return, ReturnItem, ReturnStatus
from resolveops.models.ticket import Ticket, TicketStatus


def seed_customer_operations(session: Session) -> bool:
    store = CustomerOperationsStore(session)
    if store.get_customer("CUST-1001") is not None:
        return False

    order_created = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
    first_capture = order_created + timedelta(minutes=1)
    second_capture = order_created + timedelta(minutes=2)
    return_created = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    return_received = datetime(2026, 9, 12, 13, 30, tzinfo=UTC)
    case_opened = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)

    store.add_customer(
        Customer(
            customer_id="CUST-1001",
            name="Maya Patel",
            email="maya.patel@example.com",
            tier=CustomerTier.GOLD,
            status=CustomerStatus.ACTIVE,
        )
    )
    store.add_order(
        Order(
            order_id="ORD-48391",
            customer_id="CUST-1001",
            status=OrderStatus.PARTIALLY_RETURNED,
            total_amount=Decimal("1499.00"),
            currency="USD",
            items=[
                OrderItem(
                    order_item_id="ITEM-1001",
                    order_id="ORD-48391",
                    sku="SKU-ESPRESSO-01",
                    name="Espresso machine",
                    quantity=1,
                    unit_price=Decimal("1299.00"),
                    currency="USD",
                ),
                OrderItem(
                    order_item_id="ITEM-1002",
                    order_id="ORD-48391",
                    sku="SKU-GRINDER-01",
                    name="Coffee grinder",
                    quantity=1,
                    unit_price=Decimal("200.00"),
                    currency="USD",
                ),
            ],
            created_at=order_created,
        )
    )
    session.flush()

    store.add_payment(
        Payment(
            payment_id="PAY-1001",
            obligation_id="OBL-ORD-48391",
            obligation_amount=Decimal("1499.00"),
            order_id="ORD-48391",
            amount=Decimal("1499.00"),
            currency="USD",
            status=PaymentStatus.CAPTURED,
            created_at=order_created,
            captured_at=first_capture,
        )
    )
    store.add_payment(
        Payment(
            payment_id="PAY-1002",
            obligation_id="OBL-ORD-48391",
            obligation_amount=Decimal("1499.00"),
            order_id="ORD-48391",
            amount=Decimal("1499.00"),
            currency="USD",
            status=PaymentStatus.CAPTURED,
            created_at=order_created + timedelta(minutes=1),
            captured_at=second_capture,
        )
    )
    store.add_return(
        Return(
            return_id="RET-3001",
            order_id="ORD-48391",
            customer_id="CUST-1001",
            status=ReturnStatus.RECEIVED,
            items=[
                ReturnItem(
                    order_item_id="ITEM-1002",
                    quantity=1,
                    reason="Customer changed their mind",
                )
            ],
            created_at=return_created,
            received_at=return_received,
        )
    )
    session.flush()

    store.add_case(
        Case(
            case_id="CASE-1001",
            customer_id="CUST-1001",
            order_id="ORD-48391",
            status=CaseStatus.IN_PROGRESS,
            issues=[
                CaseIssue(
                    issue_id="ISSUE-1001",
                    case_id="CASE-1001",
                    order_id="ORD-48391",
                    issue_type=CaseIssueType.DUPLICATE_CHARGE,
                    status=CaseIssueStatus.INVESTIGATING,
                    payment_ids=["PAY-1001", "PAY-1002"],
                    evidence=[
                        CaseIssueEvidence(
                            evidence_id="EVIDENCE-1001",
                            source="payment simulator",
                            reference_id="PAY-1001",
                            summary="First payment is captured for 1499.00 USD",
                            collected_at=case_opened,
                        ),
                        CaseIssueEvidence(
                            evidence_id="EVIDENCE-1002",
                            source="payment simulator",
                            reference_id="PAY-1002",
                            summary="Second payment is captured one minute later",
                            collected_at=case_opened,
                        ),
                    ],
                    reported_at=case_opened,
                ),
                CaseIssue(
                    issue_id="ISSUE-1002",
                    case_id="CASE-1001",
                    order_id="ORD-48391",
                    issue_type=CaseIssueType.MISSING_RETURN_REFUND,
                    status=CaseIssueStatus.INVESTIGATING,
                    return_id="RET-3001",
                    evidence=[
                        CaseIssueEvidence(
                            evidence_id="EVIDENCE-1003",
                            source="return simulator",
                            reference_id="RET-3001",
                            summary="Returned item was received four days ago",
                            collected_at=case_opened,
                        )
                    ],
                    reported_at=case_opened,
                ),
            ],
            opened_at=case_opened,
            updated_at=case_opened,
        )
    )
    session.flush()

    store.add_refund(
        Refund(
            refund_id="REF-2001",
            payment_id="PAY-1001",
            order_id="ORD-48391",
            issue_id="ISSUE-1002",
            return_id="RET-3001",
            amount=Decimal("200.00"),
            currency="USD",
            status=RefundStatus.PENDING,
            kind=RefundKind.RETURN,
            reason="Refund for returned coffee grinder",
            created_at=case_opened,
        )
    )
    session.flush()
    return True


def seed_simulator_resources(session: Session) -> bool:
    store = SimulatorStore(session)
    created = False
    created_at = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)

    if store.get_ticket("TKT-4001") is None:
        store.add_ticket(
            Ticket(
                ticket_id="TKT-4001",
                case_id="CASE-1001",
                subject="Duplicate payment and missing return refund",
                description=(
                    "Customer reports two visible payments and has not received the refund "
                    "for a returned coffee grinder."
                ),
                status=TicketStatus.IN_PROGRESS,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        created = True

    policies = [
        Policy(
            policy_id="POLICY-DUPLICATE-CHARGE-V1",
            title="Duplicate charge investigation",
            version=1,
            status=PolicyStatus.ACTIVE,
            issue_types=[CaseIssueType.DUPLICATE_CHARGE],
            content=(
                "A customer report alone does not authorize a refund. Confirm that distinct "
                "payments for the same order, amount, and currency were captured. Check for an "
                "existing refund and another legitimate payment explanation before proposing action."
            ),
            source="Customer Operations policy simulator",
            effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        Policy(
            policy_id="POLICY-RETURN-REFUND-V3",
            title="Returned item refund investigation",
            version=3,
            status=PolicyStatus.ACTIVE,
            issue_types=[CaseIssueType.MISSING_RETURN_REFUND],
            content=(
                "Verify the returned item, received state, paid amount, and any existing return "
                "refund. Keep return refunds separate from duplicate-charge refunds."
            ),
            source="Customer Operations policy simulator",
            effective_at=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        Policy(
            policy_id="POLICY-REFUND-AMOUNT-V1",
            title="Incorrect return refund amount",
            version=1,
            status=PolicyStatus.ACTIVE,
            issue_types=[CaseIssueType.INCORRECT_REFUND_AMOUNT],
            content=(
                "Verify the received return, item value, currency and completed refunds. "
                "Subtract completed amounts and propose only the remaining eligible balance."
            ),
            source="Customer Operations policy simulator",
            effective_at=datetime(2026, 6, 1, tzinfo=UTC),
        ),
        Policy(
            policy_id="POLICY-CANCELLED-ORDER-CHARGE-V1",
            title="Cancelled order captured charge",
            version=1,
            status=PolicyStatus.ACTIVE,
            issue_types=[CaseIssueType.CANCELLED_ORDER_CHARGE],
            content=(
                "Verify cancelled order state, a full captured obligation and all existing refunds. "
                "Only the remaining captured value may be proposed."
            ),
            source="Customer Operations policy simulator",
            effective_at=datetime(2026, 6, 1, tzinfo=UTC),
        ),
    ]
    for policy in policies:
        if store.get_policy(policy.policy_id) is None:
            store.add_policy(policy)
            created = True

    if store.get_notification("NOTE-5001") is None:
        store.add_notification(
            Notification(
                notification_id="NOTE-5001",
                case_id="CASE-1001",
                customer_id="CUST-1001",
                channel=NotificationChannel.EMAIL,
                recipient="maya.patel@example.com",
                message="We are investigating both issues on your order separately.",
                status=NotificationStatus.SENT,
                created_at=created_at,
                sent_at=created_at + timedelta(minutes=1),
            )
        )
        created = True

    session.flush()
    return created


def seed_all(session: Session) -> bool:
    from resolveops.database.demo_scenarios import seed_demo_scenarios

    customer_data_created = seed_customer_operations(session)
    simulator_data_created = seed_simulator_resources(session)
    employee_it_created = seed_employee_it(session)
    demo_scenarios_created = seed_demo_scenarios(session)
    return (
        customer_data_created
        or simulator_data_created
        or employee_it_created
        or demo_scenarios_created
    )


def seed_employee_it(session: Session) -> bool:
    if session.get(EmployeeRecord, "EMP-2001") is not None:
        return False
    requested_at = datetime(2026, 9, 20, 14, 0, tzinfo=UTC)
    manager = EmployeeRecord(
        employee_id="EMP-2000",
        name="Anika Rao",
        work_email="anika.rao@example.com",
        manager_employee_id=None,
        status=EmploymentStatus.ACTIVE,
    )
    employee = EmployeeRecord(
        employee_id="EMP-2001",
        name="Devin Chen",
        work_email="devin.chen@example.com",
        manager_employee_id=manager.employee_id,
        status=EmploymentStatus.ACTIVE,
    )
    session.add_all([manager, employee])
    session.flush()
    team = TeamRecord(
        team_id="TEAM-ML-PLATFORM",
        name="ML Platform",
        manager_employee_id=manager.employee_id,
    )
    session.add(team)
    session.flush()
    session.add_all(
        [
            EmployeeTeamMembershipRecord(
                employee_id=employee.employee_id,
                team_id=team.team_id,
                status=MembershipStatus.ACTIVE,
                joined_at=requested_at - timedelta(days=2),
            ),
            EnterpriseIdentityRecord(
                identity_id="IDENTITY-2001",
                employee_id=employee.employee_id,
                username="devin.chen",
                status=IdentityStatus.ACTIVE,
                mfa_enrolled=True,
            ),
            DirectoryGroupRecord(
                group_id="GROUP-ML-PLATFORM-DEVELOPERS",
                name="ML Platform Developers",
                team_id=team.team_id,
                purpose="Controls write access to ML Platform source repositories.",
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            GitAccountRecord(
                git_account_id="GIT-ACCOUNT-2001",
                identity_id="IDENTITY-2001",
                username="devin-chen",
                status=GitAccountStatus.ACTIVE,
            ),
            GitRepositoryRecord(
                repository_id="REPO-ML-PLATFORM",
                name="ml-platform",
                owning_team_id=team.team_id,
                required_group_id="GROUP-ML-PLATFORM-DEVELOPERS",
            ),
        ]
    )
    session.flush()
    access_case = ITAccessCaseRecord(
        case_id="ITCASE-2001",
        employee_id=employee.employee_id,
        access_request_id="ACCESS-REQUEST-2001",
        status=ITCaseStatus.ACTION_PENDING,
        opened_at=requested_at,
        updated_at=requested_at + timedelta(hours=1),
    )
    session.add(access_case)
    session.flush()
    session.add_all(
        [
            ITAccessRequestRecord(
                access_request_id=access_case.access_request_id,
                case_id=access_case.case_id,
                employee_id=employee.employee_id,
                identity_id="IDENTITY-2001",
                target_team_id=team.team_id,
                repository_id="REPO-ML-PLATFORM",
                requested_level=RepositoryAccessLevel.WRITE,
                justification="New ML Platform engineer requires repository access for assigned work.",
                status=AccessRequestStatus.APPROVED,
                requested_at=requested_at,
                approved_by=manager.employee_id,
                approved_at=requested_at + timedelta(hours=1),
            ),
            ITTicketRecord(
                ticket_id="IT-TICKET-2001",
                case_id=access_case.case_id,
                subject="ML Platform repository access",
                description="Employee joined ML Platform but cannot access its source repository.",
                status=ITTicketStatus.IN_PROGRESS,
                created_at=requested_at,
                updated_at=requested_at,
            ),
        ]
    )
    session.flush()
    return True


def seed_additional_it_cases(session: Session) -> bool:
    created = False
    base = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
    definitions = (
        ("2002", "Elena Brooks", AccessRequestStatus.PENDING_APPROVAL, ITCaseStatus.OPEN, True),
        ("2003", "Marcus Reed", AccessRequestStatus.FULFILLED, ITCaseStatus.RESOLVED, True),
        ("2004", "Priya Shah", AccessRequestStatus.APPROVED, ITCaseStatus.INVESTIGATING, False),
    )
    for offset, (suffix, name, request_status, case_status, mfa_enrolled) in enumerate(definitions):
        employee_id = f"EMP-{suffix}"
        if session.get(EmployeeRecord, employee_id) is not None:
            continue
        requested_at = base + timedelta(hours=offset * 3)
        identity_id = f"IDENTITY-{suffix}"
        git_account_id = f"GIT-ACCOUNT-{suffix}"
        case_id = f"ITCASE-{suffix}"
        request_id = f"ACCESS-REQUEST-{suffix}"
        employee = EmployeeRecord(
            employee_id=employee_id,
            name=name,
            work_email=f"{name.lower().replace(' ', '.')}@example.com",
            manager_employee_id="EMP-2000",
            status=EmploymentStatus.ACTIVE,
        )
        session.add(employee)
        session.flush()
        session.add_all(
            [
                EmployeeTeamMembershipRecord(
                    employee_id=employee_id,
                    team_id="TEAM-ML-PLATFORM",
                    status=MembershipStatus.ACTIVE,
                    joined_at=requested_at - timedelta(days=1),
                ),
                EnterpriseIdentityRecord(
                    identity_id=identity_id,
                    employee_id=employee_id,
                    username=name.lower().replace(" ", "."),
                    status=IdentityStatus.ACTIVE,
                    mfa_enrolled=mfa_enrolled,
                ),
            ]
        )
        session.flush()
        session.add(
            GitAccountRecord(
                git_account_id=git_account_id,
                identity_id=identity_id,
                username=name.lower().replace(" ", "-"),
                status=GitAccountStatus.ACTIVE,
            )
        )
        session.flush()
        access_case = ITAccessCaseRecord(
            case_id=case_id,
            employee_id=employee_id,
            access_request_id=request_id,
            status=case_status,
            opened_at=requested_at,
            updated_at=requested_at + timedelta(minutes=45),
        )
        session.add(access_case)
        session.flush()
        approved = request_status != AccessRequestStatus.PENDING_APPROVAL
        session.add_all(
            [
                ITAccessRequestRecord(
                    access_request_id=request_id,
                    case_id=case_id,
                    employee_id=employee_id,
                    identity_id=identity_id,
                    target_team_id="TEAM-ML-PLATFORM",
                    repository_id="REPO-ML-PLATFORM",
                    requested_level=RepositoryAccessLevel.WRITE,
                    justification="Repository access required for an assigned platform project.",
                    status=request_status,
                    requested_at=requested_at,
                    approved_by="EMP-2000" if approved else None,
                    approved_at=requested_at + timedelta(minutes=20) if approved else None,
                ),
                ITTicketRecord(
                    ticket_id=f"IT-TICKET-{suffix}",
                    case_id=case_id,
                    subject="ML Platform repository access",
                    description="Validate manager approval, identity, MFA, group, and repository state.",
                    status=ITTicketStatus.RESOLVED
                    if request_status == AccessRequestStatus.FULFILLED
                    else ITTicketStatus.IN_PROGRESS,
                    created_at=requested_at,
                    updated_at=requested_at + timedelta(minutes=45),
                ),
            ]
        )
        if request_status == AccessRequestStatus.FULFILLED:
            session.add_all(
                [
                    DirectoryGroupMembershipRecord(
                        membership_id=f"GROUP-MEMBERSHIP-{suffix}",
                        group_id="GROUP-ML-PLATFORM-DEVELOPERS",
                        identity_id=identity_id,
                        status=MembershipStatus.ACTIVE,
                        granted_at=requested_at + timedelta(minutes=30),
                    ),
                    GitRepositoryAccessRecord(
                        access_id=f"REPOSITORY-ACCESS-{suffix}",
                        repository_id="REPO-ML-PLATFORM",
                        git_account_id=git_account_id,
                        level=RepositoryAccessLevel.WRITE,
                        status=MembershipStatus.ACTIVE,
                        granted_at=requested_at + timedelta(minutes=32),
                    ),
                    ITNotificationRecord(
                        notification_id=f"IT-NOTIFICATION-{suffix}",
                        case_id=case_id,
                        employee_id=employee_id,
                        recipient=employee.work_email,
                        message="Repository access is active and verified.",
                        status=ITNotificationStatus.SENT,
                        sent_at=requested_at + timedelta(minutes=45),
                    ),
                ]
            )
        session.flush()
        created = True
    return created


def main() -> None:
    from pathlib import Path

    from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
    from resolveops.knowledge.ingestion import ingest_directory

    settings = get_settings()
    engine = create_database_engine(settings.resolved_database_url())
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        created = seed_all(session)
        knowledge = ingest_directory(
            session,
            Path("domain_packs"),
            FeatureHashEmbeddingProvider(dimensions=128),
            ingested_at=datetime.now(UTC),
        )
    print("Seed data created." if created else "Seed data already exists.")
    print(
        f"Demo policy index ready: {knowledge.created_documents} documents and "
        f"{knowledge.created_embeddings} embeddings added."
    )


if __name__ == "__main__":
    main()

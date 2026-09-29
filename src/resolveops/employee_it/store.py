from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.employee_it_records import (
    DirectoryGroupMembershipRecord,
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
from resolveops.employee_it.models import (
    DirectoryGroupMembership,
    Employee,
    EmployeeAccessSnapshot,
    EmployeeTeamMembership,
    EnterpriseIdentity,
    GitAccount,
    GitRepository,
    GitRepositoryAccess,
    ITAccessCase,
    ITAccessRequest,
    ITNotification,
    ITTicket,
    Team,
)
from resolveops.operations.errors import ResourceNotFoundError


class EmployeeITStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_snapshot(self, case_id: str) -> EmployeeAccessSnapshot:
        case = self._required(ITAccessCaseRecord, case_id, "IT access case")
        request = self._required(ITAccessRequestRecord, case.access_request_id, "IT access request")
        employee = self._required(EmployeeRecord, case.employee_id, "employee")
        identity = self._required(
            EnterpriseIdentityRecord, request.identity_id, "enterprise identity"
        )
        team = self._required(TeamRecord, request.target_team_id, "team")
        git_account = self.session.scalar(
            select(GitAccountRecord).where(GitAccountRecord.identity_id == identity.identity_id)
        )
        repository = self._required(GitRepositoryRecord, request.repository_id, "Git repository")
        ticket = self.session.scalar(
            select(ITTicketRecord).where(ITTicketRecord.case_id == case.case_id)
        )
        if git_account is None or ticket is None:
            raise ResourceNotFoundError(
                "it_case_incomplete", "IT access case is missing required linked resources"
            )
        team_membership = self.session.get(
            EmployeeTeamMembershipRecord,
            {"employee_id": employee.employee_id, "team_id": team.team_id},
        )
        group_membership = self.session.scalar(
            select(DirectoryGroupMembershipRecord).where(
                DirectoryGroupMembershipRecord.group_id == repository.required_group_id,
                DirectoryGroupMembershipRecord.identity_id == identity.identity_id,
            )
        )
        repository_access = self.session.scalar(
            select(GitRepositoryAccessRecord).where(
                GitRepositoryAccessRecord.repository_id == repository.repository_id,
                GitRepositoryAccessRecord.git_account_id == git_account.git_account_id,
            )
        )
        notifications = list(
            self.session.scalars(
                select(ITNotificationRecord)
                .where(ITNotificationRecord.case_id == case.case_id)
                .order_by(ITNotificationRecord.sent_at, ITNotificationRecord.notification_id)
            )
        )
        return EmployeeAccessSnapshot(
            employee=self._employee(employee),
            team=self._team(team),
            team_membership=(self._team_membership(team_membership) if team_membership else None),
            identity=self._identity(identity),
            git_account=self._git_account(git_account),
            repository=self._repository(repository),
            access_case=self._case(case),
            access_request=self._request(request),
            group_membership=(
                self._group_membership(group_membership) if group_membership else None
            ),
            repository_access=(
                self._repository_access(repository_access) if repository_access else None
            ),
            ticket=self._ticket(ticket),
            notifications=[self._notification(item) for item in notifications],
        )

    def get_employee(self, employee_id: str) -> Employee | None:
        record = self.session.get(EmployeeRecord, employee_id)
        return self._employee(record) if record is not None else None

    def _required[RecordT](
        self, record_type: type[RecordT], identifier: str, label: str
    ) -> RecordT:
        record = self.session.get(record_type, identifier)
        if record is None:
            raise ResourceNotFoundError(
                "resource_not_found", f"{label} {identifier} does not exist"
            )
        return record

    @staticmethod
    def _employee(record: EmployeeRecord) -> Employee:
        return Employee(
            employee_id=record.employee_id,
            name=record.name,
            work_email=record.work_email,
            manager_employee_id=record.manager_employee_id,
            status=record.status,
        )

    @staticmethod
    def _team(record: TeamRecord) -> Team:
        return Team(
            team_id=record.team_id,
            name=record.name,
            manager_employee_id=record.manager_employee_id,
        )

    @staticmethod
    def _team_membership(record: EmployeeTeamMembershipRecord) -> EmployeeTeamMembership:
        return EmployeeTeamMembership(
            employee_id=record.employee_id,
            team_id=record.team_id,
            status=record.status,
            joined_at=record.joined_at,
        )

    @staticmethod
    def _identity(record: EnterpriseIdentityRecord) -> EnterpriseIdentity:
        return EnterpriseIdentity(
            identity_id=record.identity_id,
            employee_id=record.employee_id,
            username=record.username,
            status=record.status,
            mfa_enrolled=record.mfa_enrolled,
        )

    @staticmethod
    def _git_account(record: GitAccountRecord) -> GitAccount:
        return GitAccount(
            git_account_id=record.git_account_id,
            identity_id=record.identity_id,
            username=record.username,
            status=record.status,
        )

    @staticmethod
    def _repository(record: GitRepositoryRecord) -> GitRepository:
        return GitRepository(
            repository_id=record.repository_id,
            name=record.name,
            owning_team_id=record.owning_team_id,
            required_group_id=record.required_group_id,
        )

    @staticmethod
    def _case(record: ITAccessCaseRecord) -> ITAccessCase:
        return ITAccessCase(
            case_id=record.case_id,
            employee_id=record.employee_id,
            access_request_id=record.access_request_id,
            status=record.status,
            opened_at=record.opened_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _request(record: ITAccessRequestRecord) -> ITAccessRequest:
        return ITAccessRequest(
            access_request_id=record.access_request_id,
            case_id=record.case_id,
            employee_id=record.employee_id,
            identity_id=record.identity_id,
            target_team_id=record.target_team_id,
            repository_id=record.repository_id,
            requested_level=record.requested_level,
            justification=record.justification,
            status=record.status,
            requested_at=record.requested_at,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
        )

    @staticmethod
    def _group_membership(
        record: DirectoryGroupMembershipRecord,
    ) -> DirectoryGroupMembership:
        return DirectoryGroupMembership(
            membership_id=record.membership_id,
            group_id=record.group_id,
            identity_id=record.identity_id,
            status=record.status,
            granted_at=record.granted_at,
        )

    @staticmethod
    def _repository_access(record: GitRepositoryAccessRecord) -> GitRepositoryAccess:
        return GitRepositoryAccess(
            access_id=record.access_id,
            repository_id=record.repository_id,
            git_account_id=record.git_account_id,
            level=record.level,
            status=record.status,
            granted_at=record.granted_at,
        )

    @staticmethod
    def _ticket(record: ITTicketRecord) -> ITTicket:
        return ITTicket(
            ticket_id=record.ticket_id,
            case_id=record.case_id,
            subject=record.subject,
            description=record.description,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _notification(record: ITNotificationRecord) -> ITNotification:
        return ITNotification(
            notification_id=record.notification_id,
            case_id=record.case_id,
            employee_id=record.employee_id,
            recipient=record.recipient,
            message=record.message,
            status=record.status,
            sent_at=record.sent_at,
        )

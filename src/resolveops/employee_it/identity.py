from sqlalchemy.orm import Session

from resolveops.database.employee_it_records import EmployeeRecord, EnterpriseIdentityRecord
from resolveops.employee_it.models import EmploymentStatus, IdentityStatus
from resolveops.operations.errors import AuthorizationError


def authenticated_employee(
    session: Session, subject_id: str, *, require_mfa: bool = False
) -> tuple[EmployeeRecord, EnterpriseIdentityRecord]:
    """Resolve a provisioned identity ID; names, email strings and role claims are not mappings."""
    identity = session.get(EnterpriseIdentityRecord, subject_id)
    employee = session.get(EmployeeRecord, identity.employee_id) if identity is not None else None
    if identity is None or employee is None:
        raise AuthorizationError(
            "employee_identity_unmapped", "The authenticated subject has no employee identity."
        )
    if identity.status != IdentityStatus.ACTIVE or employee.status != EmploymentStatus.ACTIVE:
        raise AuthorizationError(
            "employee_identity_inactive", "An active employee and enterprise identity are required."
        )
    if require_mfa and not identity.mfa_enrolled:
        raise AuthorizationError("approver_mfa_required", "The approver must have MFA enrolled.")
    return employee, identity

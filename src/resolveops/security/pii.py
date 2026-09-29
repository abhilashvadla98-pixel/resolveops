from resolveops.employee_it.models import Employee, EmployeeAccessSnapshot
from resolveops.models.customer import Customer
from resolveops.models.notification import Notification


def mask_name(name: str) -> str:
    return " ".join(f"{part[0]}***" for part in name.split() if part)


def mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "[redacted]"
    return f"{local[:1]}***@{domain}"


def redact_customer(customer: Customer) -> Customer:
    return customer.model_copy(
        update={
            "name": mask_name(customer.name),
            "email": mask_email(str(customer.email)),
        }
    )


def redact_notification(notification: Notification) -> Notification:
    return notification.model_copy(update={"recipient": "[redacted]"})


def redact_employee(employee: Employee) -> Employee:
    return employee.model_copy(
        update={
            "name": mask_name(employee.name),
            "work_email": mask_email(str(employee.work_email)),
        }
    )


def redact_employee_access_snapshot(
    snapshot: EmployeeAccessSnapshot,
) -> EmployeeAccessSnapshot:
    return snapshot.model_copy(
        update={
            "employee": redact_employee(snapshot.employee),
            "identity": snapshot.identity.model_copy(update={"username": "redacted"}),
            "git_account": snapshot.git_account.model_copy(update={"username": "redacted"}),
            "notifications": [
                item.model_copy(update={"recipient": mask_email(str(item.recipient))})
                for item in snapshot.notifications
            ],
        }
    )

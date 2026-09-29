from decimal import Decimal

from resolveops.operations.errors import (
    ApprovalRequiredError,
    AuthorizationError,
)
from resolveops.operations.models import Actor, ActorRole, Permission

ROLE_PERMISSIONS: dict[ActorRole, frozenset[Permission]] = {
    ActorRole.AGENT: frozenset(
        {
            Permission.READ_OPERATIONS,
            Permission.SEND_NOTIFICATION,
            Permission.CREATE_TICKET,
        }
    ),
    ActorRole.OPERATOR: frozenset(Permission),
    ActorRole.APPROVER: frozenset(Permission),
    ActorRole.SYSTEM: frozenset(Permission),
}

USD_REFUND_LIMITS: dict[ActorRole, Decimal] = {
    ActorRole.OPERATOR: Decimal("500.00"),
    ActorRole.APPROVER: Decimal("5000.00"),
    ActorRole.SYSTEM: Decimal("5000.00"),
}


def has_approval_path(amount: Decimal, currency: str) -> bool:
    """Return whether an authorized approval role can cover this refund."""
    if currency != "USD":
        return False
    return any(amount <= USD_REFUND_LIMITS[role] for role in (ActorRole.APPROVER, ActorRole.SYSTEM))


def require_permission(actor: Actor, permission: Permission) -> None:
    if not has_permission(actor, permission):
        raise AuthorizationError(
            "permission_denied",
            f"role {actor.role.value} does not have {permission.value} permission",
        )


def has_permission(actor: Actor, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[actor.role]


def require_refund_limit(actor: Actor, amount: Decimal, currency: str) -> None:
    if currency != "USD":
        raise ApprovalRequiredError(
            "currency_approval_required",
            f"refund limits are not configured for {currency}",
        )

    limit = USD_REFUND_LIMITS.get(actor.role)
    if limit is None or amount > limit:
        raise ApprovalRequiredError(
            "refund_approval_required",
            f"{amount} {currency} exceeds the {actor.role.value} refund limit",
        )

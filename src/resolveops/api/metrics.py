from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST

from resolveops.api.dependencies import get_principal
from resolveops.observability.metrics import render_metrics
from resolveops.operations.models import ActorRole
from resolveops.security.models import SecurityPrincipal

router = APIRouter()

METRICS_ROLES = frozenset({ActorRole.OPERATOR, ActorRole.APPROVER, ActorRole.SYSTEM})


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(
    principal: Annotated[SecurityPrincipal, Depends(get_principal)],
) -> Response:
    if principal.role not in METRICS_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="metrics access denied",
        )
    return Response(
        content=render_metrics(),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )

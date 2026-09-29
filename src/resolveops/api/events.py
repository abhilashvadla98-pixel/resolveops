from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from resolveops.api.dependencies import get_tenant_webhook_registry
from resolveops.events.errors import EventConflictError, WebhookAuthenticationError
from resolveops.events.models import EventReceipt, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.security.webhooks import TenantWebhookRegistry, WebhookTenantError

router = APIRouter(prefix="/events/v1", tags=["events"])


@router.post("/refund-status", response_model=EventReceipt)
async def receive_refund_status_event(
    request: Request,
    webhook_registry: Annotated[TenantWebhookRegistry, Depends(get_tenant_webhook_registry)],
    tenant_id: Annotated[str | None, Header(alias="X-ResolveOps-Tenant")] = None,
    timestamp: Annotated[str | None, Header(alias="X-ResolveOps-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-ResolveOps-Signature")] = None,
) -> EventReceipt:
    body = await request.body()
    try:
        verifier, session_factory = webhook_registry.context(tenant_id)
        verifier.verify(body, timestamp=timestamp, signature=signature)
    except (WebhookAuthenticationError, WebhookTenantError) as exc:
        code = (
            exc.code
            if isinstance(exc, WebhookAuthenticationError)
            else "invalid_webhook_authentication"
        )
        message = (
            exc.message
            if isinstance(exc, WebhookAuthenticationError)
            else "webhook authentication failed"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": code, "message": message},
        ) from exc

    try:
        event = RefundStatusChangedEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False, include_context=False),
        ) from exc

    try:
        return RefundEventProcessor(session_factory).process(event)
    except EventConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

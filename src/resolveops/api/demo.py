from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from resolveops.api.dependencies import (
    get_demo_session_authenticator,
    get_principal,
    get_tenant_session,
)
from resolveops.config import get_demo_settings, get_settings
from resolveops.database.demo_scenarios import list_demo_scenarios, reset_demo_scenarios
from resolveops.database.records import RefundRecord
from resolveops.database.session import create_session_factory
from resolveops.events.models import RefundStatusChangedData, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.models.refund import RefundStatus
from resolveops.security.demo_sessions import DemoSession, DemoSessionAuthenticator
from resolveops.security.models import SecurityPrincipal

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


class DemoScenario(DomainModel):
    scenario_id: Identifier
    title: NonEmptyText
    domain: Identifier
    case_id: Identifier
    description: NonEmptyText


class SimulatedRefundStatus(DomainModel):
    status: Literal["completed", "failed"]


@router.post("/refunds/{refund_id}/status")
def simulate_refund_status(
    refund_id: str, body: SimulatedRefundStatus, session: DatabaseSession, principal: Principal
) -> dict[str, str]:
    """Sandbox-only event uses the settlement processor, never a real payment API."""
    _require_demo_principal(principal)
    refund = session.get(RefundRecord, refund_id)
    if refund is None:
        raise HTTPException(status_code=404, detail="refund not found in this sandbox")
    desired = RefundStatus(body.status)
    if refund.status == desired:
        return {"status": desired.value, "mode": "synthetic_provider", "refund_id": refund_id}
    if refund.status not in {RefundStatus.PENDING, RefundStatus.PROCESSING}:
        raise HTTPException(
            status_code=409, detail="A final provider outcome cannot be overwritten."
        )
    now = datetime.now(UTC)
    event = RefundStatusChangedEvent(
        event_id=f"DEMO-EVT-{uuid4().hex}",
        source="synthetic_payment_provider",
        occurred_at=now,
        data=RefundStatusChangedData(
            refund_id=refund_id,
            provider_reference=f"SIM-{refund_id}",
            status=RefundStatus.COMPLETED if body.status == "completed" else RefundStatus.FAILED,
            completed_at=now if desired == RefundStatus.COMPLETED else None,
        ),
    )
    engine = session.get_bind()
    from sqlalchemy import Engine

    if not isinstance(engine, Engine):
        raise HTTPException(status_code=500, detail="Sandbox database is unavailable")
    receipt = RefundEventProcessor(create_session_factory(engine)).process(event)
    if receipt.status.value != "processed":
        raise HTTPException(status_code=409, detail=receipt.message)
    return {"status": desired.value, "mode": "synthetic_provider", "refund_id": refund_id}


@router.post("/session", response_model=DemoSession, status_code=status.HTTP_201_CREATED)
def create_demo_session(
    authenticator: Annotated[
        DemoSessionAuthenticator | None, Depends(get_demo_session_authenticator)
    ],
) -> DemoSession:
    if authenticator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="demo is not enabled")
    demo_settings = get_demo_settings()
    settings = get_settings()
    return authenticator.create().model_copy(
        update={
            "isolated_workspace": (
                demo_settings.demo_enabled and demo_settings.demo_isolated_sessions
            ),
            "data_mode": "synthetic",
            "execution_mode": (
                "live_model_enabled"
                if (
                    settings.integrated_agents_enabled
                    and settings.demo_agent_max_runs_per_session > 0
                )
                or settings.agent_queue_enabled
                else "rules_only"
            ),
        }
    )


def _require_demo_principal(principal: SecurityPrincipal) -> None:
    if principal.authentication_method != "demo_session":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="demo session required")


@router.get("/scenarios", response_model=list[DemoScenario])
def get_scenarios(session: DatabaseSession, principal: Principal) -> list[DemoScenario]:
    _require_demo_principal(principal)
    return [
        DemoScenario(
            scenario_id=item.scenario_id,
            title=item.title,
            domain=item.domain,
            case_id=item.case_id,
            description=item.description,
        )
        for item in list_demo_scenarios(session)
    ]


@router.post("/reset", response_model=list[DemoScenario])
def reset_scenarios(session: DatabaseSession, principal: Principal) -> list[DemoScenario]:
    _require_demo_principal(principal)
    reset_demo_scenarios(session)
    session.commit()
    return get_scenarios(session, principal)

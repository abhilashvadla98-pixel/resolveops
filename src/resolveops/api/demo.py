from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from resolveops.api.dependencies import (
    get_demo_session_authenticator,
    get_principal,
    get_tenant_session,
)
from resolveops.database.demo_scenarios import list_demo_scenarios, reset_demo_scenarios
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
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


@router.post("/session", response_model=DemoSession, status_code=status.HTTP_201_CREATED)
def create_demo_session(
    authenticator: Annotated[
        DemoSessionAuthenticator | None, Depends(get_demo_session_authenticator)
    ],
) -> DemoSession:
    if authenticator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="demo is not enabled")
    return authenticator.create()


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

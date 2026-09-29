from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from resolveops.api.dependencies import get_demo_session_authenticator
from resolveops.security.demo_sessions import DemoSession, DemoSessionAuthenticator

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


@router.post("/session", response_model=DemoSession, status_code=status.HTTP_201_CREATED)
def create_demo_session(
    authenticator: Annotated[
        DemoSessionAuthenticator | None, Depends(get_demo_session_authenticator)
    ],
) -> DemoSession:
    if authenticator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="demo is not enabled")
    return authenticator.create()

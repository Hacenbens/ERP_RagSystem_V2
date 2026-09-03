"""
Auth routes — Sprint 3
POST /auth/register, /auth/login, /auth/request-password-reset, /auth/reset-password

All routes are public (in AuthMiddleware._PUBLIC_PATHS).
The AuthUseCase is resolved from the DI container.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.infrastructure.auth.user_repository import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from src.domain.user_role import UserRole
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)
    role: UserRole = Field(default=UserRole.REPORTING_ANALYST)
    tenant_id: str = Field(default="default", min_length=1)


class RegisterResponse(BaseModel):
    user_id: str
    username: str
    role: UserRole
    tenant_id: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    tenant_id: str


class PasswordResetRequest(BaseModel):
    username: str


class PasswordResetConfirm(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=8)


# ---------------------------------------------------------------------------
# Dependency: resolve AuthUseCase from DI container
# ---------------------------------------------------------------------------

def _get_auth_use_case(request: Request):
    """Resolve AuthUseCase from the app's DI container (set in lifespan)."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        # Fallback: build on-demand (useful in tests without full app startup)
        from src.infrastructure.di.factory import build_container
        container = build_container()
        request.app.state.container = container
    return container.get("auth_use_case")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    body: RegisterRequest,
    use_case=Depends(_get_auth_use_case),
) -> RegisterResponse:
    try:
        result = use_case.register(
            username=body.username,
            password=body.password,
            role=body.role,
            tenant_id=body.tenant_id,
        )
        logger.info("auth.register.success", username=body.username, role=body.role)
        return RegisterResponse(**result.__dict__)
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and receive JWT",
)
async def login(
    body: LoginRequest,
    use_case=Depends(_get_auth_use_case),
) -> LoginResponse:
    try:
        result = use_case.login(username=body.username, password=body.password)
        logger.info("auth.login.success", username=body.username)
        return LoginResponse(**result.__dict__)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/request-password-reset",
    summary="Request a password reset token",
)
async def request_password_reset(
    body: PasswordResetRequest,
    use_case=Depends(_get_auth_use_case),
) -> dict:
    try:
        result = use_case.request_password_reset(body.username)
        logger.info("auth.password_reset.requested", username=body.username)
        return {"reset_token": result.reset_token, "message": result.message}
    except UserNotFoundError:
        # Don't reveal whether user exists — return same response
        return {"message": "If that username exists, a reset token has been issued."}


@router.post(
    "/reset-password",
    summary="Reset password using a reset token",
)
async def reset_password(
    body: PasswordResetConfirm,
    use_case=Depends(_get_auth_use_case),
) -> dict:
    try:
        return use_case.reset_password(
            reset_token=body.reset_token,
            new_password=body.new_password,
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )


__all__ = ["router"]

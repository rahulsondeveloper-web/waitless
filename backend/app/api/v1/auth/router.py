from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.api.deps import ClaimsDep, ClientDep, CurrentUser, SessionDep
from app.core.config import get_settings
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    SwitchTenantRequest,
)
from app.services import auth as auth_service
from app.services.auth import IssuedTokens

router = APIRouter(tags=["auth"])

REFRESH_COOKIE = "wl_refresh"
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _cookie_path() -> str:
    return f"{get_settings().api_prefix}/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=s.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=s.is_production,
        samesite="strict",
        path=_cookie_path(),
    )


async def _auth_response(session: SessionDep, response: Response, tokens: IssuedTokens) -> AuthResponse:
    _set_refresh_cookie(response, tokens.refresh_token)
    me = await auth_service.build_me(session, tokens.user, tokens.tenant_id)
    return AuthResponse(access_token=tokens.access_token, expires_at=tokens.access_expires_at, me=me)


@router.post("/auth/login", response_model=AuthResponse, summary="Sign in with email/mobile and password")
async def login(body: LoginRequest, session: SessionDep, response: Response, client: ClientDep) -> AuthResponse:
    tokens = await auth_service.login_with_password(session, body.identifier, body.password, client)
    return await _auth_response(session, response, tokens)


@router.post("/auth/otp/send", response_model=OtpSendResponse, summary="Send a one-time code to a mobile number")
async def otp_send(body: OtpSendRequest, session: SessionDep) -> OtpSendResponse:
    return await auth_service.send_otp(session, body.phone)


@router.post("/auth/otp/verify", response_model=AuthResponse, summary="Verify the code and sign in (creates account)")
async def otp_verify(
    body: OtpVerifyRequest, session: SessionDep, response: Response, client: ClientDep
) -> AuthResponse:
    tokens = await auth_service.verify_otp(session, body.phone, body.code, body.full_name, client)
    return await _auth_response(session, response, tokens)


@router.post("/auth/refresh", response_model=AuthResponse, summary="Rotate the refresh cookie, get a new access token")
async def refresh(
    session: SessionDep, response: Response, client: ClientDep, wl_refresh: RefreshCookie = None
) -> AuthResponse:
    tokens = await auth_service.rotate_refresh_token(session, wl_refresh, client)
    return await _auth_response(session, response, tokens)


@router.post("/auth/switch-tenant", response_model=AuthResponse, summary="Choose the active restaurant")
async def switch_tenant(
    body: SwitchTenantRequest,
    session: SessionDep,
    response: Response,
    client: ClientDep,
    user: CurrentUser,
    wl_refresh: RefreshCookie = None,
) -> AuthResponse:
    tokens = await auth_service.rotate_refresh_token(
        session, wl_refresh, client, tenant_override=body.tenant_id, switch_tenant=True, expected_user_id=user.id
    )
    return await _auth_response(session, response, tokens)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out this device")
async def logout(session: SessionDep, response: Response, wl_refresh: RefreshCookie = None) -> Response:
    await auth_service.logout(session, wl_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=_cookie_path())
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/auth/password/change", status_code=status.HTTP_204_NO_CONTENT, summary="Change password")
async def change_password(body: ChangePasswordRequest, session: SessionDep, user: CurrentUser) -> Response:
    await auth_service.change_password(session, user, body.current_password, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse, summary="Current user, memberships, active restaurant and permissions")
async def me(session: SessionDep, user: CurrentUser, claims: ClaimsDep) -> MeResponse:
    return await auth_service.build_me(session, user, claims.tenant_id)

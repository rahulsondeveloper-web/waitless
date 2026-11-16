from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.deps import ClientDep, SessionDep
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.profile import BrandingOut, GalleryOut, StorefrontOut
from app.schemas.tenancy import RegistrationResponse, RestaurantRegistration, SlugAvailability, TenantOut
from app.services import profile as profile_service
from app.services import registration

router = APIRouter(prefix="/public", tags=["public"])


@router.post(
    "/restaurants/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a restaurant (PRD §4). The owner signs in afterwards with email/mobile + password.",
)
async def register_restaurant(
    body: RestaurantRegistration, session: SessionDep, client: ClientDep
) -> RegistrationResponse:
    if client.ip:
        limit = get_settings().register_limit_per_hour
        await rate_limit.hit(f"register:{client.ip}", limit=limit, window_seconds=3600)
    tenant, _owner = await registration.register_restaurant(session, body, ip=client.ip)
    return RegistrationResponse(
        tenant=TenantOut.model_validate(tenant),
        message="Registration received. You can sign in and complete your profile while WaitLess reviews it.",
    )


@router.get(
    "/restaurants/{slug}",
    response_model=StorefrontOut,
    summary="Public storefront: profile, branding, branches with hours, social links (published restaurants only)",
)
async def storefront(slug: Annotated[str, Path(max_length=60)], session: SessionDep) -> StorefrontOut:
    return await profile_service.public_storefront(session, slug)


@router.get("/restaurants/{slug}/branding", response_model=BrandingOut, summary="Logo and theme tokens")
async def storefront_branding(slug: Annotated[str, Path(max_length=60)], session: SessionDep) -> BrandingOut:
    return await profile_service.public_branding(session, slug)


@router.get("/restaurants/{slug}/gallery", response_model=GalleryOut, summary="Gallery photos (up to 5)")
async def storefront_gallery(slug: Annotated[str, Path(max_length=60)], session: SessionDep) -> GalleryOut:
    return await profile_service.public_gallery(session, slug)


@router.get("/slug-availability", response_model=SlugAvailability, summary="Check a restaurant web address")
async def slug_availability(
    session: SessionDep,
    slug: str | None = Query(default=None, max_length=80),
    name: str | None = Query(default=None, max_length=120),
    city: str | None = Query(default=None, max_length=80),
) -> SlugAvailability:
    if slug:
        clean, available = await registration.check_slug(session, slug)
        suggestion = None if available else await registration.suggest_slug(session, name or slug, city)
        return SlugAvailability(slug=clean, available=available, suggestion=suggestion)
    suggestion = await registration.suggest_slug(session, name or "restaurant", city)
    return SlugAvailability(slug=suggestion, available=True, suggestion=suggestion)

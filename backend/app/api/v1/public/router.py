import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from app.api.deps import ClientDep, SessionDep
from app.api.http_cache import etagged
from app.core import rate_limit
from app.core.config import get_settings
from app.schemas.discovery import ContactRequest, ContactResponse, DiscoveryFilters, DiscoveryPage
from app.schemas.menu import PublicItemsPage, PublicMenu
from app.schemas.profile import BrandingOut, GalleryOut, StorefrontOut
from app.schemas.tenancy import RegistrationResponse, RestaurantRegistration, SlugAvailability, TenantOut
from app.services import discovery, registration
from app.services import profile as profile_service

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
    from app.core.errors import AppError
    from app.services.saas import platform_settings

    if not (await platform_settings(session))["allow_registration"]:
        raise AppError(
            "New restaurant sign-ups are paused. Please contact WaitLess.", code="REGISTRATION_CLOSED", status_code=403
        )
    tenant, _owner = await registration.register_restaurant(session, body, ip=client.ip)
    return RegistrationResponse(
        tenant=TenantOut.model_validate(tenant),
        message="Registration received. You can sign in and complete your profile while WaitLess reviews it.",
    )


@router.get("/restaurants", response_model=DiscoveryPage, summary="Discover restaurants (published only)")
async def discover_restaurants(
    session: SessionDep,
    q: str | None = Query(default=None, max_length=80),
    city: str | None = Query(default=None, max_length=80),
    cuisine: str | None = Query(default=None, max_length=60),
    restaurant_type: str | None = Query(default=None, alias="type", max_length=60),
    open_now: bool = False,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float | None = Query(default=None, gt=0, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=50),
) -> DiscoveryPage:
    return await discovery.discover(
        session,
        q=q,
        city=city,
        cuisine=cuisine,
        restaurant_type=restaurant_type,
        open_now=open_now,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        page=page,
        page_size=page_size,
    )


@router.get("/discovery/filters", response_model=DiscoveryFilters, summary="Cities, cuisines and types for filters")
async def discovery_filters(session: SessionDep) -> DiscoveryFilters:
    return await discovery.filters(session)


@router.post("/contact", response_model=ContactResponse, status_code=201, summary="WaitLess contact form")
async def contact(body: ContactRequest, session: SessionDep, client: ClientDep) -> ContactResponse:
    if client.ip:
        await rate_limit.hit(f"contact:{client.ip}", limit=get_settings().contact_limit_per_hour, window_seconds=3600)
    return await discovery.submit_contact(session, body)


MenuLimit = Annotated[int | None, Query(ge=1, le=100, description="Dishes per category; more via /items")]
VegOnly = Annotated[bool, Query()]
MenuSearch = Annotated[str, Query(max_length=60)]


@router.get("/restaurants/{slug}/menu", response_model=PublicMenu, summary="Menu (active categories with dishes)")
async def storefront_menu(
    slug: Annotated[str, Path(max_length=60)],
    session: SessionDep,
    request: Request,
    limit: MenuLimit = None,
    veg: VegOnly = False,
    q: MenuSearch = "",
) -> Response:
    """Without `limit` every dish is returned. With it, each category carries its first `limit` dishes and
    `item_count`; the storefront loads the rest in batches while the guest scrolls. ETag / 304 supported."""
    menu = await profile_service.public_menu(session, slug)
    return etagged(request, profile_service.page_menu(menu, limit=limit, veg=veg, q=q))


@router.get(
    "/restaurants/{slug}/menu/categories/{category_id}/items",
    response_model=PublicItemsPage,
    summary="Next batch of a category's dishes",
)
async def storefront_menu_items(
    slug: Annotated[str, Path(max_length=60)],
    category_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    veg: VegOnly = False,
    q: MenuSearch = "",
) -> Response:
    menu = await profile_service.public_menu(session, slug)
    return etagged(request, profile_service.page_items(menu, category_id, offset=offset, limit=limit, veg=veg, q=q))


@router.get(
    "/restaurants/{slug}",
    response_model=StorefrontOut,
    summary="Public storefront: profile, branding, branches with hours, social links (published restaurants only)",
)
async def storefront(slug: Annotated[str, Path(max_length=60)], session: SessionDep, request: Request) -> Response:
    return etagged(request, await profile_service.public_storefront(session, slug))


@router.get("/restaurants/{slug}/branding", response_model=BrandingOut, summary="Logo and theme tokens")
async def storefront_branding(
    slug: Annotated[str, Path(max_length=60)], session: SessionDep, request: Request
) -> Response:
    return etagged(request, await profile_service.public_branding(session, slug))


@router.get("/restaurants/{slug}/gallery", response_model=GalleryOut, summary="Gallery photos (up to 5)")
async def storefront_gallery(
    slug: Annotated[str, Path(max_length=60)], session: SessionDep, request: Request
) -> Response:
    return etagged(request, await profile_service.public_gallery(session, slug))


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


@router.get("/content", summary="WaitLess website content (Super Admin editable)")
async def website_content(session: SessionDep) -> dict[str, Any]:
    from app.services.platform import public_content

    return await public_content(session)

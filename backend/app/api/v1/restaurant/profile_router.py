"""Restaurant profile, branding, gallery, hours, social links and publishing (PRD §5)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.deps import SessionDep, require_permission
from app.schemas.profile import (
    BranchLocationUpdate,
    BrandingOut,
    BrandingUpdate,
    GalleryCaptionUpdate,
    GalleryOut,
    GalleryReorder,
    HoursOut,
    HoursUpdate,
    ProfileOut,
    ProfileUpdate,
    PublishChecklist,
    PublishRequest,
    SocialLinkOut,
    SocialLinksUpdate,
)
from app.schemas.tenancy import BranchOut
from app.services import profile as svc
from app.services.access import TenantContext

router = APIRouter(prefix="/restaurant", tags=["restaurant profile"])

ProfileView = Annotated[TenantContext, Depends(require_permission("restaurant.profile.view"))]
ProfileManage = Annotated[TenantContext, Depends(require_permission("restaurant.profile.manage"))]
BrandingManage = Annotated[TenantContext, Depends(require_permission("restaurant.branding.manage"))]
GalleryManage = Annotated[TenantContext, Depends(require_permission("restaurant.gallery.manage"))]
BranchesManage = Annotated[TenantContext, Depends(require_permission("branches.manage"))]
ImageFile = Annotated[UploadFile, File(description="JPEG, PNG or WebP")]


# Profile
@router.get("/profile", response_model=ProfileOut, summary="Restaurant profile")
async def get_profile(session: SessionDep, ctx: ProfileView) -> ProfileOut:
    return await svc.get_profile(session, ctx)


@router.put("/profile", response_model=ProfileOut, summary="Update restaurant profile")
async def update_profile(body: ProfileUpdate, session: SessionDep, ctx: ProfileManage) -> ProfileOut:
    return await svc.update_profile(session, ctx, body)


@router.post("/branding/cover", response_model=ProfileOut, summary="Upload or replace the cover image")
async def upload_cover(file: ImageFile, session: SessionDep, ctx: BrandingManage) -> ProfileOut:
    return await svc.set_cover(session, ctx, file)


@router.delete("/branding/cover", response_model=ProfileOut, summary="Remove the cover image")
async def delete_cover(session: SessionDep, ctx: BrandingManage) -> ProfileOut:
    return await svc.remove_cover(session, ctx)


# Branding
@router.get("/branding", response_model=BrandingOut, summary="Logo and theme")
async def get_branding(session: SessionDep, ctx: ProfileView) -> BrandingOut:
    return await svc.get_branding(session, ctx)


@router.put("/branding", response_model=BrandingOut, summary="Update theme colours, button style and mode")
async def update_branding(body: BrandingUpdate, session: SessionDep, ctx: BrandingManage) -> BrandingOut:
    return await svc.update_branding(session, ctx, body)


@router.post("/branding/reset", response_model=BrandingOut, summary="Restore the default WaitLess theme")
async def reset_branding(session: SessionDep, ctx: BrandingManage) -> BrandingOut:
    return await svc.reset_branding(session, ctx)


@router.post("/branding/logo", response_model=BrandingOut, summary="Upload or replace the logo")
async def upload_logo(file: ImageFile, session: SessionDep, ctx: BrandingManage) -> BrandingOut:
    return await svc.set_logo(session, ctx, file)


@router.delete("/branding/logo", response_model=BrandingOut, summary="Remove the logo")
async def delete_logo(session: SessionDep, ctx: BrandingManage) -> BrandingOut:
    return await svc.remove_logo(session, ctx)


# Gallery
@router.get("/gallery", response_model=GalleryOut, summary="Gallery photos (max 5)")
async def get_gallery(session: SessionDep, ctx: ProfileView) -> GalleryOut:
    return await svc.get_gallery(session, ctx)


@router.post("/gallery", response_model=GalleryOut, status_code=201, summary="Add a photo (409 when 5 exist)")
async def add_gallery(
    file: ImageFile, session: SessionDep, ctx: GalleryManage, caption: Annotated[str, Form(max_length=160)] = ""
) -> GalleryOut:
    return await svc.add_gallery_image(session, ctx, file, caption)


@router.put("/gallery/order", response_model=GalleryOut, summary="Reorder photos")
async def reorder_gallery(body: GalleryReorder, session: SessionDep, ctx: GalleryManage) -> GalleryOut:
    return await svc.reorder_gallery(session, ctx, body.ids)


@router.put("/gallery/{item_id}", response_model=GalleryOut, summary="Replace a photo")
async def replace_gallery(item_id: uuid.UUID, file: ImageFile, session: SessionDep, ctx: GalleryManage) -> GalleryOut:
    return await svc.replace_gallery_image(session, ctx, item_id, file)


@router.patch("/gallery/{item_id}", response_model=GalleryOut, summary="Edit a caption")
async def caption_gallery(
    item_id: uuid.UUID, body: GalleryCaptionUpdate, session: SessionDep, ctx: GalleryManage
) -> GalleryOut:
    return await svc.update_gallery_caption(session, ctx, item_id, body.caption)


@router.delete("/gallery/{item_id}", response_model=GalleryOut, summary="Delete a photo")
async def delete_gallery(item_id: uuid.UUID, session: SessionDep, ctx: GalleryManage) -> GalleryOut:
    return await svc.delete_gallery_image(session, ctx, item_id)


# Branch location & hours
@router.patch("/branches/{branch_id}", response_model=BranchOut, summary="Edit branch address and map location")
async def update_branch(
    branch_id: uuid.UUID, body: BranchLocationUpdate, session: SessionDep, ctx: BranchesManage
) -> BranchOut:
    return await svc.update_branch_location(session, ctx, branch_id, body)


@router.get("/branches/{branch_id}/hours", response_model=HoursOut, summary="Opening hours of a branch")
async def get_hours(branch_id: uuid.UUID, session: SessionDep, ctx: ProfileView) -> HoursOut:
    return await svc.get_hours(session, ctx, branch_id)


@router.put("/branches/{branch_id}/hours", response_model=HoursOut, summary="Set opening hours (all 7 days)")
async def set_hours(branch_id: uuid.UUID, body: HoursUpdate, session: SessionDep, ctx: ProfileManage) -> HoursOut:
    return await svc.set_hours(session, ctx, branch_id, body)


# Social links
@router.get("/social-links", response_model=list[SocialLinkOut], summary="Social media links")
async def get_social(session: SessionDep, ctx: ProfileView) -> list[SocialLinkOut]:
    return await svc.get_social_links(session, ctx)


@router.put("/social-links", response_model=list[SocialLinkOut], summary="Replace social media links")
async def set_social(body: SocialLinksUpdate, session: SessionDep, ctx: ProfileManage) -> list[SocialLinkOut]:
    return await svc.set_social_links(session, ctx, body)


# Publishing
@router.get("/publish-checklist", response_model=PublishChecklist, summary="What is left before going live")
async def checklist(session: SessionDep, ctx: ProfileView) -> PublishChecklist:
    return await svc.publish_checklist(session, ctx)


@router.post("/publish", response_model=PublishChecklist, summary="Publish or unpublish the storefront")
async def publish(body: PublishRequest, session: SessionDep, ctx: ProfileManage) -> PublishChecklist:
    return await svc.set_published(session, ctx, body.published)


@router.get("/geocode", summary="Find an address on the map (Nominatim, or Google when configured)")
async def geocode(ctx: ProfileManage, q: str = Query(min_length=3, max_length=200)) -> list[dict]:
    """Server-side, cached 30 days and limited to 30 lookups per restaurant per hour."""
    from dataclasses import asdict

    from app.core import rate_limit
    from app.integrations.maps import geocode as lookup

    await rate_limit.hit(f"geocode:{ctx.tenant_id}", limit=30, window_seconds=3600)
    return [asdict(p) for p in await lookup(q)]

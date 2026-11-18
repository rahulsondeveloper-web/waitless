"""Menu management (PRD §7) and storefront preview for the restaurant team."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import SessionDep, require_permission
from app.schemas.menu import (
    AdminMenu,
    BranchOverrideIn,
    CategoryIn,
    CategoryPatch,
    ItemIn,
    ItemOptionsIn,
    ItemOut,
    ItemPatch,
    MealTypeIn,
    MealTypePatch,
    PublicMenu,
    StockPatch,
    SubcategoryIn,
    SubcategoryPatch,
)
from app.schemas.profile import StorefrontOut
from app.services import menu as svc
from app.services import profile as profile_svc
from app.services.access import TenantContext

router = APIRouter(prefix="/restaurant", tags=["restaurant menu"])

MenuManage = Annotated[TenantContext, Depends(require_permission("menu.manage"))]
StockToggle = Annotated[TenantContext, Depends(require_permission("menu.availability.toggle"))]
OrdersView = Annotated[TenantContext, Depends(require_permission("orders.view"))]
ProfileView = Annotated[TenantContext, Depends(require_permission("restaurant.profile.view"))]


@router.get("/menu", response_model=AdminMenu, summary="Full menu structure and dishes (including archived)")
async def get_menu(session: SessionDep, ctx: MenuManage) -> AdminMenu:
    return await svc.admin_menu(session, ctx)


# Meal types
@router.post("/menu/meal-types", response_model=AdminMenu, status_code=201)
async def create_meal_type(body: MealTypeIn, session: SessionDep, ctx: MenuManage) -> AdminMenu:
    return await svc.create_meal_type(session, ctx, body)


@router.patch("/menu/meal-types/{meal_id}", response_model=AdminMenu)
async def update_meal_type(meal_id: uuid.UUID, body: MealTypePatch, session: SessionDep, ctx: MenuManage) -> AdminMenu:
    return await svc.update_meal_type(session, ctx, meal_id, body)


# Categories & subcategories
@router.post("/menu/categories", response_model=AdminMenu, status_code=201)
async def create_category(body: CategoryIn, session: SessionDep, ctx: MenuManage) -> AdminMenu:
    return await svc.create_category(session, ctx, body)


@router.patch("/menu/categories/{category_id}", response_model=AdminMenu)
async def update_category(
    category_id: uuid.UUID, body: CategoryPatch, session: SessionDep, ctx: MenuManage
) -> AdminMenu:
    return await svc.update_category(session, ctx, category_id, body)


@router.delete("/menu/categories/{category_id}", response_model=AdminMenu, summary="Delete an empty category")
async def delete_category(category_id: uuid.UUID, session: SessionDep, ctx: MenuManage) -> AdminMenu:
    return await svc.delete_category(session, ctx, category_id)


@router.post("/menu/categories/{category_id}/subcategories", response_model=AdminMenu, status_code=201)
async def create_subcategory(
    category_id: uuid.UUID, body: SubcategoryIn, session: SessionDep, ctx: MenuManage
) -> AdminMenu:
    return await svc.create_subcategory(session, ctx, category_id, body)


@router.patch("/menu/subcategories/{sub_id}", response_model=AdminMenu)
async def update_subcategory(
    sub_id: uuid.UUID, body: SubcategoryPatch, session: SessionDep, ctx: MenuManage
) -> AdminMenu:
    return await svc.update_subcategory(session, ctx, sub_id, body)


@router.delete("/menu/subcategories/{sub_id}", response_model=AdminMenu)
async def delete_subcategory(sub_id: uuid.UUID, session: SessionDep, ctx: MenuManage) -> AdminMenu:
    return await svc.delete_subcategory(session, ctx, sub_id)


# Items
@router.post("/menu/items", response_model=ItemOut, status_code=201, summary="Add a dish")
async def create_item(body: ItemIn, session: SessionDep, ctx: MenuManage) -> ItemOut:
    return await svc.create_item(session, ctx, body)


@router.patch("/menu/items/{item_id}", response_model=ItemOut, summary="Edit a dish")
async def update_item(item_id: uuid.UUID, body: ItemPatch, session: SessionDep, ctx: MenuManage) -> ItemOut:
    return await svc.update_item(session, ctx, item_id, body)


@router.put("/menu/items/{item_id}/options", response_model=ItemOut, summary="Variants, add-ons and time windows")
async def set_options(item_id: uuid.UUID, body: ItemOptionsIn, session: SessionDep, ctx: MenuManage) -> ItemOut:
    return await svc.set_options(session, ctx, item_id, body)


@router.put(
    "/menu/items/{item_id}/branches/{branch_id}", response_model=ItemOut, summary="Price / availability at one branch"
)
async def set_branch_override(
    item_id: uuid.UUID, branch_id: uuid.UUID, body: BranchOverrideIn, session: SessionDep, ctx: MenuManage
) -> ItemOut:
    return await svc.set_branch_override(session, ctx, item_id, branch_id, body)


@router.patch("/menu/items/{item_id}/stock", response_model=ItemOut, summary="Mark sold out / available")
async def set_stock(item_id: uuid.UUID, body: StockPatch, session: SessionDep, ctx: StockToggle) -> ItemOut:
    return await svc.set_stock(session, ctx, item_id, body.is_available)


@router.post("/menu/items/{item_id}/archive", response_model=ItemOut, summary="Archive (hide) a dish")
async def archive_item(item_id: uuid.UUID, session: SessionDep, ctx: MenuManage) -> ItemOut:
    return await svc.archive_item(session, ctx, item_id, True)


@router.post("/menu/items/{item_id}/restore", response_model=ItemOut, summary="Restore an archived dish")
async def restore_item(item_id: uuid.UUID, session: SessionDep, ctx: MenuManage) -> ItemOut:
    return await svc.archive_item(session, ctx, item_id, False)


@router.post("/menu/items/{item_id}/image", response_model=ItemOut, summary="Upload or replace the dish photo")
async def upload_item_image(
    item_id: uuid.UUID, file: Annotated[UploadFile, File()], session: SessionDep, ctx: MenuManage
) -> ItemOut:
    return await svc.set_item_image(session, ctx, item_id, file)


@router.delete("/menu/items/{item_id}/image", response_model=ItemOut, summary="Remove the dish photo")
async def remove_item_image(item_id: uuid.UUID, session: SessionDep, ctx: MenuManage) -> ItemOut:
    return await svc.remove_item_image(session, ctx, item_id)


@router.post("/menu/categories/{category_id}/image", response_model=AdminMenu, summary="Upload the category photo")
async def upload_category_image(
    category_id: uuid.UUID, file: Annotated[UploadFile, File()], session: SessionDep, ctx: MenuManage
) -> AdminMenu:
    await svc.set_category_image(session, ctx, category_id, file)
    return await svc.admin_menu(session, ctx)


@router.delete("/menu/categories/{category_id}/image", response_model=AdminMenu, summary="Back to the default photo")
async def remove_category_image(category_id: uuid.UUID, session: SessionDep, ctx: MenuManage) -> AdminMenu:
    await svc.remove_category_image(session, ctx, category_id)
    return await svc.admin_menu(session, ctx)


# Owner preview of the storefront (works before publishing)
@router.get("/storefront", response_model=StorefrontOut, summary="Preview your storefront data (even unpublished)")
async def preview_storefront(session: SessionDep, ctx: ProfileView) -> StorefrontOut:
    return await profile_svc.preview_storefront(session, ctx)


@router.get("/storefront/menu", response_model=PublicMenu, summary="Preview your public menu")
async def preview_menu(session: SessionDep, ctx: ProfileView) -> PublicMenu:
    return await profile_svc.preview_menu(session, ctx)

"""Inventory, suppliers, purchases, transfers, recipes and inventory reports (PRD §8). Plan feature `inventory`."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import SessionDep, TenantCtx, require_feature, require_permission
from app.core.errors import ForbiddenError
from app.schemas.inventory import (
    AlertsOut,
    CategoryIn,
    CategoryOut,
    ItemIn,
    ItemOut,
    MovementIn,
    MovementOut,
    PaymentIn,
    PurchaseIn,
    PurchaseOut,
    ReceiveIn,
    RecipeIn,
    RecipeOut,
    ReportOut,
    StockRow,
    SupplierIn,
    SupplierOut,
    TransferIn,
    TransferOut,
)
from app.services import inventory as svc
from app.services import inventory_reports as reports
from app.services import purchasing
from app.services.access import TenantContext

router = APIRouter(
    prefix="/restaurant", tags=["restaurant inventory"], dependencies=[Depends(require_feature("inventory"))]
)

View = Annotated[TenantContext, Depends(require_permission("inventory.view"))]
Adjust = Annotated[TenantContext, Depends(require_permission("inventory.adjust"))]
Transfer = Annotated[TenantContext, Depends(require_permission("inventory.transfer"))]
Suppliers = Annotated[TenantContext, Depends(require_permission("suppliers.manage"))]
Purchases = Annotated[TenantContext, Depends(require_permission("purchases.manage"))]
Recipes = Annotated[TenantContext, Depends(require_permission("recipes.manage"))]


def _any(ctx: TenantContext, *perms: str) -> None:
    if not any(ctx.has(p) for p in perms):
        raise ForbiddenError("You do not have permission to do this.", code="PERMISSION_DENIED")


# ---------- categories & items ----------


@router.get("/inventory/categories", response_model=list[CategoryOut])
async def list_categories(session: SessionDep, ctx: View) -> list[CategoryOut]:
    return await svc.list_categories(session)


@router.post("/inventory/categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryIn, session: SessionDep, ctx: Adjust) -> CategoryOut:
    return await svc.save_category(session, ctx, body)


@router.put("/inventory/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: uuid.UUID, body: CategoryIn, session: SessionDep, ctx: Adjust) -> CategoryOut:
    return await svc.save_category(session, ctx, body, category_id)


@router.delete("/inventory/categories/{category_id}", status_code=204)
async def delete_category(category_id: uuid.UUID, session: SessionDep, ctx: Adjust) -> Response:
    await svc.delete_category(session, category_id)
    return Response(status_code=204)


@router.get("/inventory/items", response_model=list[ItemOut], summary="Inventory items (raw materials)")
async def list_items(session: SessionDep, ctx: TenantCtx) -> list[ItemOut]:
    _any(ctx, "inventory.view", "purchases.manage", "recipes.manage")
    return await svc.list_items(session)


@router.post("/inventory/items", response_model=ItemOut, status_code=201)
async def create_item(body: ItemIn, session: SessionDep, ctx: Adjust) -> ItemOut:
    return await svc.save_item(session, ctx, body)


@router.put("/inventory/items/{item_id}", response_model=ItemOut)
async def update_item(item_id: uuid.UUID, body: ItemIn, session: SessionDep, ctx: Adjust) -> ItemOut:
    return await svc.save_item(session, ctx, body, item_id)


# ---------- stock & movements ----------


@router.get("/inventory/stock", response_model=list[StockRow], summary="Stock of one branch")
async def stock(session: SessionDep, ctx: View, branch_id: uuid.UUID, include_inactive: bool = False) -> list[StockRow]:
    return await svc.stock(session, ctx, branch_id, include_inactive)


@router.post("/inventory/movements", response_model=MovementOut, status_code=201, summary="Record a stock change")
async def record_movement(body: MovementIn, session: SessionDep, ctx: Adjust) -> MovementOut:
    """Opening stock, additions, wastage, damage, returns, count corrections. A reason is required."""
    return await svc.record_movement(session, ctx, body)


@router.get("/inventory/movements", response_model=list[MovementOut], summary="The stock ledger")
async def movements(
    session: SessionDep,
    ctx: View,
    branch_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
    type: Annotated[list[str] | None, Query()] = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[MovementOut]:
    return await svc.list_movements(
        session, ctx, branch_id, item_id=item_id, types=type, start=start, end=end, limit=limit
    )


@router.get("/inventory/alerts", response_model=AlertsOut, summary="Low, out of stock and expiring")
async def alerts(
    session: SessionDep, ctx: View, branch_id: uuid.UUID, days: int = Query(default=7, ge=1, le=90)
) -> AlertsOut:
    return await svc.alerts(session, ctx, branch_id, days)


@router.get("/inventory/reports/{kind}", response_model=ReportOut)
async def report(
    kind: str,
    session: SessionDep,
    ctx: View,
    branch_id: uuid.UUID,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> ReportOut:
    """current · valuation · movements · consumption · wastage · purchases · low_stock · expiry"""
    return await reports.report(session, ctx, kind, branch_id, start, end)


# ---------- transfers ----------


@router.get("/inventory/transfers", response_model=list[TransferOut])
async def list_transfers(session: SessionDep, ctx: View, branch_id: uuid.UUID) -> list[TransferOut]:
    return await svc.list_transfers(session, ctx, branch_id)


@router.post("/inventory/transfers", response_model=TransferOut, status_code=201, summary="Send stock to a branch")
async def send_transfer(body: TransferIn, session: SessionDep, ctx: Transfer) -> TransferOut:
    return await svc.send_transfer(session, ctx, body)


@router.post("/inventory/transfers/{transfer_id}/receive", response_model=TransferOut)
async def receive_transfer(transfer_id: uuid.UUID, session: SessionDep, ctx: Transfer) -> TransferOut:
    return await svc.finish_transfer(session, ctx, transfer_id, receive=True)


@router.post("/inventory/transfers/{transfer_id}/cancel", response_model=TransferOut)
async def cancel_transfer(transfer_id: uuid.UUID, session: SessionDep, ctx: Transfer) -> TransferOut:
    return await svc.finish_transfer(session, ctx, transfer_id, receive=False)


# ---------- suppliers ----------


@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(session: SessionDep, ctx: TenantCtx) -> list[SupplierOut]:
    _any(ctx, "suppliers.manage", "purchases.manage", "inventory.adjust")
    return await purchasing.list_suppliers(session)


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
async def create_supplier(body: SupplierIn, session: SessionDep, ctx: Suppliers) -> SupplierOut:
    return await purchasing.save_supplier(session, ctx, body)


@router.put("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(supplier_id: uuid.UUID, body: SupplierIn, session: SessionDep, ctx: Suppliers) -> SupplierOut:
    return await purchasing.save_supplier(session, ctx, body, supplier_id)


# ---------- purchases ----------


@router.get("/purchases", response_model=list[PurchaseOut])
async def list_purchases(
    session: SessionDep, ctx: Purchases, branch_id: uuid.UUID | None = None, supplier_id: uuid.UUID | None = None
) -> list[PurchaseOut]:
    return await purchasing.list_purchases(session, ctx, branch_id, supplier_id)


@router.post("/purchases", response_model=PurchaseOut, status_code=201, summary="New purchase order")
async def create_purchase(body: PurchaseIn, session: SessionDep, ctx: Purchases) -> PurchaseOut:
    return await purchasing.save_purchase(session, ctx, body)


@router.put("/purchases/{purchase_id}", response_model=PurchaseOut)
async def update_purchase(purchase_id: uuid.UUID, body: PurchaseIn, session: SessionDep, ctx: Purchases) -> PurchaseOut:
    return await purchasing.save_purchase(session, ctx, body, purchase_id)


@router.post("/purchases/{purchase_id}/order", response_model=PurchaseOut, summary="Mark as ordered")
async def order_purchase(purchase_id: uuid.UUID, session: SessionDep, ctx: Purchases) -> PurchaseOut:
    return await purchasing.set_status(session, ctx, purchase_id, "ordered")


@router.post("/purchases/{purchase_id}/cancel", response_model=PurchaseOut)
async def cancel_purchase(purchase_id: uuid.UUID, session: SessionDep, ctx: Purchases) -> PurchaseOut:
    return await purchasing.set_status(session, ctx, purchase_id, "cancelled")


@router.post("/purchases/{purchase_id}/receive", response_model=PurchaseOut, summary="Goods received → stock in")
async def receive_purchase(purchase_id: uuid.UUID, body: ReceiveIn, session: SessionDep, ctx: Purchases) -> PurchaseOut:
    return await purchasing.receive(session, ctx, purchase_id, body)


@router.post("/purchases/{purchase_id}/payments", response_model=PurchaseOut, summary="Record a supplier payment")
async def pay_purchase(purchase_id: uuid.UUID, body: PaymentIn, session: SessionDep, ctx: Purchases) -> PurchaseOut:
    return await purchasing.add_payment(session, ctx, purchase_id, body)


# ---------- recipes ----------


@router.get("/menu/items/{menu_item_id}/recipe", response_model=RecipeOut)
async def get_recipe(menu_item_id: uuid.UUID, session: SessionDep, ctx: Recipes) -> RecipeOut:
    return await svc.get_recipe(session, menu_item_id)


@router.put("/menu/items/{menu_item_id}/recipe", response_model=RecipeOut, summary="Replace the dish's ingredients")
async def set_recipe(menu_item_id: uuid.UUID, body: RecipeIn, session: SessionDep, ctx: Recipes) -> RecipeOut:
    return await svc.set_recipe(session, ctx, menu_item_id, body)

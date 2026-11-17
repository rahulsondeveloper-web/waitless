"""Branches, employees, roles, tables, table sessions and the dashboard (PRD §11, §15)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import SessionDep, TenantCtxAnyStatus, require_permission
from app.schemas.staff import (
    BranchCreate,
    BranchStatus,
    PermissionOut,
    RoleIn,
    RoleOut,
    RolePatch,
    StaffInvite,
    StaffOut,
    StaffUpdate,
)
from app.schemas.tables import (
    BoardOut,
    DashboardOut,
    SeatedOut,
    SeatIn,
    SectionIn,
    SectionOut,
    SectionPatch,
    SessionOut,
    TableIn,
    TableOut,
    TablePatch,
    TableStatusIn,
    TransferIn,
)
from app.schemas.tenancy import BranchOut
from app.services import staff as staff_svc
from app.services import tables as tables_svc
from app.services.access import TenantContext

router = APIRouter(prefix="/restaurant", tags=["restaurant operations"])

BranchesManage = Annotated[TenantContext, Depends(require_permission("branches.manage"))]
StaffManage = Annotated[TenantContext, Depends(require_permission("staff.manage"))]
TablesConfigure = Annotated[TenantContext, Depends(require_permission("tables.configure"))]
TablesOperate = Annotated[TenantContext, Depends(require_permission("tables.operate"))]


# ---------- dashboard ----------
@router.get("/dashboard", response_model=DashboardOut, summary="Today's numbers (tables now; more each phase)")
async def dashboard(
    session: SessionDep, ctx: TablesOperate, branch_id: uuid.UUID | None = Query(default=None)
) -> DashboardOut:
    return await tables_svc.dashboard(session, ctx, branch_id)


# ---------- branches ----------
@router.post("/branches", response_model=BranchOut, status_code=201, summary="Open a new branch (plan limit applies)")
async def create_branch(body: BranchCreate, session: SessionDep, ctx: BranchesManage) -> BranchOut:
    return await staff_svc.create_branch(session, ctx, body)


@router.patch("/branches/{branch_id}/status", response_model=BranchOut, summary="Activate or deactivate a branch")
async def branch_status(
    branch_id: uuid.UUID, body: BranchStatus, session: SessionDep, ctx: BranchesManage
) -> BranchOut:
    return await staff_svc.set_branch_active(session, ctx, branch_id, body.is_active)


# ---------- staff ----------
@router.get("/staff", response_model=list[StaffOut], summary="Employees")
async def list_staff(session: SessionDep, ctx: StaffManage) -> list[StaffOut]:
    return await staff_svc.list_staff(session, ctx)


@router.post("/staff", response_model=StaffOut, status_code=201, summary="Add an employee (signs in with mobile OTP)")
async def invite_staff(body: StaffInvite, session: SessionDep, ctx: StaffManage) -> StaffOut:
    return await staff_svc.invite_staff(session, ctx, body)


@router.patch("/staff/{membership_id}", response_model=StaffOut, summary="Change role, branches or status")
async def update_staff(membership_id: uuid.UUID, body: StaffUpdate, session: SessionDep, ctx: StaffManage) -> StaffOut:
    return await staff_svc.update_staff(session, ctx, membership_id, body)


@router.delete("/staff/{membership_id}", status_code=204, summary="Remove an employee from this restaurant")
async def remove_staff(membership_id: uuid.UUID, session: SessionDep, ctx: StaffManage) -> Response:
    await staff_svc.remove_staff(session, ctx, membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- roles ----------
@router.get("/permissions", response_model=list[PermissionOut], summary="Permission catalogue for custom roles")
async def permissions(session: SessionDep, _ctx: TenantCtxAnyStatus) -> list[PermissionOut]:
    return await staff_svc.list_permissions(session)


@router.get("/roles", response_model=list[RoleOut], summary="Built-in and custom roles")
async def list_roles(session: SessionDep, ctx: StaffManage) -> list[RoleOut]:
    return await staff_svc.list_roles(session, ctx)


@router.post("/roles", response_model=RoleOut, status_code=201, summary="Create a custom role")
async def create_role(body: RoleIn, session: SessionDep, ctx: StaffManage) -> RoleOut:
    return await staff_svc.create_role(session, ctx, body)


@router.patch("/roles/{role_id}", response_model=RoleOut, summary="Edit a custom role")
async def update_role(role_id: uuid.UUID, body: RolePatch, session: SessionDep, ctx: StaffManage) -> RoleOut:
    return await staff_svc.update_role(session, ctx, role_id, body)


@router.delete("/roles/{role_id}", status_code=204, summary="Delete an unused custom role")
async def delete_role(role_id: uuid.UUID, session: SessionDep, ctx: StaffManage) -> Response:
    await staff_svc.delete_role(session, ctx, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- sections & tables ----------
@router.get("/sections", response_model=list[SectionOut], summary="Sections of a branch")
async def list_sections(session: SessionDep, ctx: TablesOperate, branch_id: uuid.UUID = Query()) -> list[SectionOut]:
    return await tables_svc.list_sections(session, ctx, branch_id)


@router.post("/sections", response_model=SectionOut, status_code=201)
async def create_section(body: SectionIn, session: SessionDep, ctx: TablesConfigure) -> SectionOut:
    return await tables_svc.create_section(session, ctx, body)


@router.patch("/sections/{section_id}", response_model=SectionOut)
async def update_section(
    section_id: uuid.UUID, body: SectionPatch, session: SessionDep, ctx: TablesConfigure
) -> SectionOut:
    return await tables_svc.update_section(session, ctx, section_id, body)


@router.delete("/sections/{section_id}", status_code=204)
async def delete_section(section_id: uuid.UUID, session: SessionDep, ctx: TablesConfigure) -> Response:
    await tables_svc.delete_section(session, ctx, section_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tables", response_model=list[TableOut], summary="All tables of a branch (including inactive)")
async def list_tables(session: SessionDep, ctx: TablesOperate, branch_id: uuid.UUID = Query()) -> list[TableOut]:
    return await tables_svc.list_tables(session, ctx, branch_id)


@router.post("/tables", response_model=TableOut, status_code=201, summary="Add a table (plan limit applies)")
async def create_table(body: TableIn, session: SessionDep, ctx: TablesConfigure) -> TableOut:
    return await tables_svc.create_table(session, ctx, body)


@router.get("/tables/board", response_model=BoardOut, summary="Live floor: tables, status, seated parties")
async def board(session: SessionDep, ctx: TablesOperate, branch_id: uuid.UUID = Query()) -> BoardOut:
    return await tables_svc.board(session, ctx, branch_id)


@router.patch("/tables/{table_id}", response_model=TableOut, summary="Edit or deactivate a table")
async def update_table(table_id: uuid.UUID, body: TablePatch, session: SessionDep, ctx: TablesConfigure) -> TableOut:
    return await tables_svc.update_table(session, ctx, table_id, body)


@router.patch("/tables/{table_id}/status", response_model=TableOut, summary="Mark reserved / cleaning / available")
async def table_status(table_id: uuid.UUID, body: TableStatusIn, session: SessionDep, ctx: TablesOperate) -> TableOut:
    return await tables_svc.set_status(session, ctx, table_id, body.status)


# ---------- table sessions ----------
@router.post("/table-sessions", response_model=SeatedOut, status_code=201, summary="Seat walk-in guests (code + PIN)")
async def seat(body: SeatIn, session: SessionDep, ctx: TablesOperate) -> SeatedOut:
    return await tables_svc.seat(session, ctx, body)


@router.post("/table-sessions/{session_id}/transfer", response_model=SessionOut, summary="Move guests to another table")
async def transfer(session_id: uuid.UUID, body: TransferIn, session: SessionDep, ctx: TablesOperate) -> SessionOut:
    return await tables_svc.transfer(session, ctx, session_id, body.table_id)


@router.post("/table-sessions/{session_id}/close", response_model=SessionOut, summary="Guests left: release the table")
async def close(session_id: uuid.UUID, session: SessionDep, ctx: TablesOperate) -> SessionOut:
    return await tables_svc.close(session, ctx, session_id)


@router.post("/table-sessions/{session_id}/pin", response_model=SeatedOut, summary="Issue a new PIN for the guests")
async def new_pin(session_id: uuid.UUID, session: SessionDep, ctx: TablesOperate) -> SeatedOut:
    return await tables_svc.new_pin(session, ctx, session_id)

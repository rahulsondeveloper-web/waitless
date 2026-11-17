"""Branches, employees and roles (PRD §3.2, §15).

Rules on top of the permission matrix (docs/04):
- Only "all"-scope holders of `staff.manage` (the Owner by default) manage roles and give access to every branch.
- A branch-scoped manager can only invite/edit staff inside their own branches and cannot grant Owner/Manager.
- Nobody can change the Owner's membership or their own (no self-lockout) through these endpoints.
Employees sign in with their mobile number + one-time code (decision D19), so no password is shared.
"""

import re
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Branch, Membership, Permission, Role, RolePermission, User, UserBranch
from app.models.tables import TableAssignment, TableSession
from app.schemas.staff import (
    BranchCreate,
    PermissionOut,
    RoleIn,
    RoleOut,
    RolePatch,
    StaffInvite,
    StaffOut,
    StaffUpdate,
)
from app.schemas.tenancy import BranchOut
from app.services.access import TenantContext
from app.services.audit import write_audit
from app.services.limits import enforce_limit
from app.services.storefront_cache import invalidate_storefront

PROTECTED_ROLE_KEYS = {"owner", "manager"}


def _is_full_admin(ctx: TenantContext) -> bool:
    return ctx.permissions.get("staff.manage") == "all"


# ---------- branches ----------


async def create_branch(session: AsyncSession, ctx: TenantContext, data: BranchCreate) -> BranchOut:
    if ctx.permissions.get("branches.manage") != "all":
        raise ForbiddenError("Only the owner can open new branches.", code="PERMISSION_DENIED")
    count = (await session.execute(select(func.count()).select_from(Branch).where(Branch.is_active))).scalar_one()
    await enforce_limit(session, ctx.tenant_id, "max_branches", count, "branches")
    if (await session.execute(select(Branch.id).where(func.lower(Branch.name) == data.name.strip().lower()))).first():
        raise ConflictError("A branch with this name already exists.", code="DUPLICATE_NAME")
    branch = Branch(tenant_id=ctx.tenant_id, is_primary=False, **data.model_dump())
    branch.name = branch.name.strip()
    session.add(branch)
    write_audit(
        session,
        action="branch.created",
        entity="branch",
        entity_id=None,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"name": branch.name},
    )
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return BranchOut.model_validate(branch)


async def set_branch_active(session: AsyncSession, ctx: TenantContext, branch_id: uuid.UUID, active: bool) -> BranchOut:
    if ctx.permissions.get("branches.manage") != "all":
        raise ForbiddenError("Only the owner can open or close branches.", code="PERMISSION_DENIED")
    branch = (await session.execute(select(Branch).where(Branch.id == branch_id))).scalar_one_or_none()
    if branch is None:
        raise NotFoundError("Branch not found.")
    if not active:
        if branch.is_primary:
            raise ConflictError("The main branch cannot be deactivated.", code="PRIMARY_BRANCH")
        busy = (
            await session.execute(
                select(func.count())
                .select_from(TableSession)
                .where(TableSession.branch_id == branch.id, TableSession.status != "closed")
            )
        ).scalar_one()
        if busy:
            raise ConflictError("Close the open tables of this branch first.", code="BRANCH_HAS_OPEN_TABLES")
    else:
        count = (await session.execute(select(func.count()).select_from(Branch).where(Branch.is_active))).scalar_one()
        if not branch.is_active:
            await enforce_limit(session, ctx.tenant_id, "max_branches", count, "branches")
    branch.is_active = active
    write_audit(
        session,
        action="branch.activated" if active else "branch.deactivated",
        entity="branch",
        entity_id=branch.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
    )
    await session.commit()
    await invalidate_storefront(ctx.tenant_slug)
    return BranchOut.model_validate(branch)


# ---------- staff ----------


async def _staff_out(session: AsyncSession, ctx: TenantContext, memberships: list[Membership]) -> list[StaffOut]:
    if not memberships:
        return []
    users = {
        u.id: u
        for u in (await session.execute(select(User).where(User.id.in_([m.user_id for m in memberships])))).scalars()
    }
    roles = {r.id: r for r in (await session.execute(select(Role))).scalars()}
    branches: dict[uuid.UUID, list[uuid.UUID]] = {}
    for mid, bid in (await session.execute(select(UserBranch.membership_id, UserBranch.branch_id))).tuples():
        branches.setdefault(mid, []).append(bid)
    out = []
    for m in memberships:
        u, r = users[m.user_id], roles[m.role_id]
        out.append(
            StaffOut(
                membership_id=m.id,
                user_id=u.id,
                full_name=u.full_name,
                phone=u.phone,
                email=u.email,
                role_id=r.id,
                role_key=r.key,
                role_name=r.name,
                status=m.status,
                all_branches=m.all_branches,
                branch_ids=sorted(branches.get(m.id, [])),
                last_login_at=u.last_login_at,
                is_owner=r.key == "owner",
                is_you=u.id == ctx.user_id,
            )
        )
    return out


async def list_staff(session: AsyncSession, ctx: TenantContext) -> list[StaffOut]:
    members = list((await session.execute(select(Membership).order_by(Membership.created_at))).scalars())
    staff = await _staff_out(session, ctx, members)
    if _is_full_admin(ctx):
        return staff
    # Branch-scoped managers see colleagues who share at least one of their branches.
    return [s for s in staff if s.is_you or (not s.all_branches and set(s.branch_ids) & ctx.branch_ids)]


async def _check_role_and_branches(
    session: AsyncSession, ctx: TenantContext, role_id: uuid.UUID, all_branches: bool, branch_ids: list[uuid.UUID]
) -> Role:
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found.")
    if role.key == "owner":
        raise ForbiddenError("The Owner role cannot be given to employees.", code="ROLE_NOT_ASSIGNABLE")
    full = _is_full_admin(ctx)
    if not full and (role.key in PROTECTED_ROLE_KEYS or all_branches):
        raise ForbiddenError(
            "Only the owner can give manager rights or access to all branches.", code="PERMISSION_DENIED"
        )
    if not all_branches:
        if not branch_ids:
            raise AppError("Choose at least one branch.", code="BRANCH_REQUIRED", status_code=422)
        found = set((await session.execute(select(Branch.id).where(Branch.id.in_(branch_ids)))).scalars())
        if found != set(branch_ids):
            raise NotFoundError("Branch not found.")
        if not full and not set(branch_ids) <= ctx.branch_ids:
            raise ForbiddenError("You can only add staff to your own branches.", code="BRANCH_FORBIDDEN")
    return role


async def _set_branches(session: AsyncSession, ctx: TenantContext, m: Membership, branch_ids: list[uuid.UUID]) -> None:
    await session.execute(delete(UserBranch).where(UserBranch.membership_id == m.id))
    if not m.all_branches:
        for bid in dict.fromkeys(branch_ids):
            session.add(UserBranch(tenant_id=ctx.tenant_id, membership_id=m.id, branch_id=bid))


async def invite_staff(session: AsyncSession, ctx: TenantContext, data: StaffInvite) -> StaffOut:
    await _check_role_and_branches(session, ctx, data.role_id, data.all_branches, data.branch_ids)
    count = (
        await session.execute(select(func.count()).select_from(Membership).where(Membership.status != "disabled"))
    ).scalar_one()
    await enforce_limit(session, ctx.tenant_id, "max_staff", count, "staff accounts")

    user = (await session.execute(select(User).where(User.phone == data.phone))).scalar_one_or_none()
    if data.email:
        by_email = (
            await session.execute(select(User).where(User.email == str(data.email).lower()))
        ).scalar_one_or_none()
        if by_email is not None and (user is None or by_email.id != user.id):
            raise ConflictError("This email belongs to a different account.", code="EMAIL_TAKEN")
    if user is None:
        user = User(
            phone=data.phone, email=str(data.email).lower() if data.email else None, full_name=data.full_name.strip()
        )
        session.add(user)
        await session.flush()
    else:
        if (await session.execute(select(Membership.id).where(Membership.user_id == user.id))).first():
            raise ConflictError("This person already works here.", code="ALREADY_STAFF")
        if not user.full_name:
            user.full_name = data.full_name.strip()
        if data.email and not user.email:
            user.email = str(data.email).lower()

    m = Membership(tenant_id=ctx.tenant_id, user_id=user.id, role_id=data.role_id, all_branches=data.all_branches)
    session.add(m)
    await session.flush()
    await _set_branches(session, ctx, m, data.branch_ids)
    write_audit(
        session,
        action="staff.invited",
        entity="membership",
        entity_id=m.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"user_id": str(user.id), "role_id": str(data.role_id)},
    )
    await session.commit()
    return (await _staff_out(session, ctx, [m]))[0]


async def _editable(session: AsyncSession, ctx: TenantContext, membership_id: uuid.UUID) -> Membership:
    m = (await session.execute(select(Membership).where(Membership.id == membership_id))).scalar_one_or_none()
    if m is None:
        raise NotFoundError("Employee not found.")
    role = await session.get(Role, m.role_id)
    if role is not None and role.key == "owner":
        raise ForbiddenError("The owner's access cannot be changed here.", code="OWNER_PROTECTED")
    if m.user_id == ctx.user_id:
        raise ForbiddenError("You cannot change your own access.", code="SELF_EDIT")
    if not _is_full_admin(ctx):
        branch_ids = set(
            (await session.execute(select(UserBranch.branch_id).where(UserBranch.membership_id == m.id))).scalars()
        )
        if m.all_branches or not branch_ids <= ctx.branch_ids or (role and role.key in PROTECTED_ROLE_KEYS):
            raise ForbiddenError("You can only manage staff of your own branches.", code="BRANCH_FORBIDDEN")
    return m


async def update_staff(
    session: AsyncSession, ctx: TenantContext, membership_id: uuid.UUID, data: StaffUpdate
) -> StaffOut:
    m = await _editable(session, ctx, membership_id)
    role_id = data.role_id or m.role_id
    all_branches = m.all_branches if data.all_branches is None else data.all_branches
    branch_ids = data.branch_ids
    if branch_ids is None:
        branch_ids = list(
            (await session.execute(select(UserBranch.branch_id).where(UserBranch.membership_id == m.id))).scalars()
        )
    await _check_role_and_branches(session, ctx, role_id, all_branches, branch_ids)
    m.role_id, m.all_branches = role_id, all_branches
    if data.status is not None:
        m.status = data.status
    await _set_branches(session, ctx, m, branch_ids)
    write_audit(
        session,
        action="staff.updated",
        entity="membership",
        entity_id=m.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff=data.model_dump(mode="json", exclude_none=True),
    )
    await session.commit()
    return (await _staff_out(session, ctx, [m]))[0]


async def remove_staff(session: AsyncSession, ctx: TenantContext, membership_id: uuid.UUID) -> None:
    m = await _editable(session, ctx, membership_id)
    write_audit(
        session,
        action="staff.removed",
        entity="membership",
        entity_id=m.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"user_id": str(m.user_id)},
    )
    await session.delete(m)  # user account stays (they may work elsewhere or be a guest)
    await session.commit()


# ---------- roles ----------


async def list_permissions(session: AsyncSession) -> list[PermissionOut]:
    rows = (await session.execute(select(Permission).order_by(Permission.module, Permission.key))).scalars()
    return [PermissionOut(key=p.key, module=p.module, description=p.description) for p in rows]


async def list_roles(session: AsyncSession, ctx: TenantContext) -> list[RoleOut]:
    roles = list((await session.execute(select(Role).order_by(Role.is_system.desc(), Role.name))).scalars())
    perms: dict[uuid.UUID, dict[str, str]] = {}
    for rid, key, scope in (
        await session.execute(select(RolePermission.role_id, RolePermission.permission_key, RolePermission.scope))
    ).tuples():
        perms.setdefault(rid, {})[key] = scope
    counts = dict(
        (await session.execute(select(Membership.role_id, func.count()).group_by(Membership.role_id))).tuples().all()
    )
    return [
        RoleOut(
            id=r.id,
            key=r.key,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            permissions=perms.get(r.id, {}),
            member_count=counts.get(r.id, 0),
        )
        for r in roles
    ]


def _require_full_admin(ctx: TenantContext) -> None:
    if not _is_full_admin(ctx):
        raise ForbiddenError("Only the owner can manage roles.", code="PERMISSION_DENIED")


async def _validate_permissions(session: AsyncSession, permissions: dict[str, str]) -> None:
    known = set((await session.execute(select(Permission.key))).scalars())
    unknown = sorted(set(permissions) - known)
    if unknown:
        raise AppError("Unknown permission.", code="UNKNOWN_PERMISSION", status_code=422, details={"keys": unknown})
    if "subscription.manage" in permissions:
        raise ForbiddenError("Billing access stays with the owner.", code="PERMISSION_NOT_DELEGABLE")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "role"


async def create_role(session: AsyncSession, ctx: TenantContext, data: RoleIn) -> RoleOut:
    _require_full_admin(ctx)
    await _validate_permissions(session, data.permissions)
    key = f"custom_{_slug(data.name)}"
    role = Role(tenant_id=ctx.tenant_id, key=key, name=data.name.strip(), description=data.description, is_system=False)
    session.add(role)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A role with this name already exists.", code="DUPLICATE_NAME") from exc
    for k, scope in data.permissions.items():
        session.add(RolePermission(role_id=role.id, permission_key=k, scope=scope))
    write_audit(
        session,
        action="role.created",
        entity="role",
        entity_id=role.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff={"name": role.name, "permissions": data.permissions},
    )
    await session.commit()
    return next(r for r in await list_roles(session, ctx) if r.id == role.id)


async def _custom_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found.")
    if role.is_system or role.tenant_id is None:
        raise ForbiddenError("Built-in roles cannot be changed.", code="SYSTEM_ROLE")
    return role


async def update_role(session: AsyncSession, ctx: TenantContext, role_id: uuid.UUID, data: RolePatch) -> RoleOut:
    _require_full_admin(ctx)
    role = await _custom_role(session, role_id)
    if data.name is not None:
        role.name = data.name.strip()
    if data.description is not None:
        role.description = data.description
    if data.permissions is not None:
        if not data.permissions:
            raise AppError("A role needs at least one permission.", code="EMPTY_ROLE", status_code=422)
        await _validate_permissions(session, data.permissions)
        await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for k, scope in data.permissions.items():
            session.add(RolePermission(role_id=role.id, permission_key=k, scope=scope))
    write_audit(
        session,
        action="role.updated",
        entity="role",
        entity_id=role.id,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        diff=data.model_dump(exclude_none=True),
    )
    await session.commit()
    return next(r for r in await list_roles(session, ctx) if r.id == role.id)


async def delete_role(session: AsyncSession, ctx: TenantContext, role_id: uuid.UUID) -> None:
    _require_full_admin(ctx)
    role = await _custom_role(session, role_id)
    used = (
        await session.execute(select(func.count()).select_from(Membership).where(Membership.role_id == role.id))
    ).scalar_one()
    if used:
        raise ConflictError("Move the employees with this role to another role first.", code="ROLE_IN_USE")
    await session.delete(role)
    await session.commit()


async def open_sessions_count(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(TableAssignment).where(TableAssignment.released_at.is_(None))
        )
    ).scalar_one()

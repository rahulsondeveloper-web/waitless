"""Idempotent sync of reference data (permissions, system roles, plans)."""

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import use_system
from app.models import Permission, Plan, PlanFeature, Role, RolePermission
from app.seeds.reference import PERMISSIONS, PLANS, SYSTEM_ROLES


async def sync_reference_data(session: AsyncSession) -> dict[str, int]:
    await use_system(session)

    # Permissions: upsert, then remove keys no longer defined.
    for key, (module, description) in PERMISSIONS.items():
        stmt = insert(Permission).values(key=key, module=module, description=description)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Permission.key], set_={"module": module, "description": description}
            )
        )
    await session.execute(delete(Permission).where(Permission.key.not_in(list(PERMISSIONS))))

    # System roles and their permission sets (fully replaced on each sync).
    for role_key, (name, description, perms) in SYSTEM_ROLES.items():
        role = (
            await session.execute(select(Role).where(Role.tenant_id.is_(None), Role.key == role_key))
        ).scalar_one_or_none()
        if role is None:
            role = Role(tenant_id=None, key=role_key, name=name, description=description, is_system=True)
            session.add(role)
            await session.flush()
        else:
            role.name, role.description, role.is_system = name, description, True
        await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for perm, scope in perms.items():
            session.add(RolePermission(role_id=role.id, permission_key=perm, scope=scope))

    # Plans: insert if missing (Super Admin owns them afterwards).
    created_plans = 0
    for spec in PLANS:
        exists = (await session.execute(select(Plan.id).where(Plan.code == spec["code"]))).scalar_one_or_none()
        if exists:
            continue
        plan = Plan(
            code=spec["code"],
            name=spec["name"],
            description=spec["description"],
            price_monthly=Decimal(spec["price_monthly"]),
            price_yearly=Decimal(spec["price_yearly"]),
            trial_days=spec["trial_days"],
            sort_order=spec["sort_order"],
        )
        session.add(plan)
        await session.flush()
        for feature, limit in spec["features"].items():
            session.add(PlanFeature(plan_id=plan.id, feature_key=feature, enabled=True, limit_value=limit))
        created_plans += 1

    await session.commit()
    return {"permissions": len(PERMISSIONS), "system_roles": len(SYSTEM_ROLES), "plans_created": created_plans}

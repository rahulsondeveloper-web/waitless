import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import CategoryMealType, MealType, MenuCategory, MenuSubcategory
from app.seeds.menu_taxonomy import CATEGORIES, MEAL_TYPES


async def seed_menu_taxonomy(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Create the PRD §7 default meal types, categories and subcategories for a new restaurant."""
    meals: dict[str, MealType] = {}
    for i, name in enumerate(MEAL_TYPES):
        meals[name] = MealType(id=uuid.uuid4(), tenant_id=tenant_id, name=name, sort_order=i)
        session.add(meals[name])
    await session.flush()
    for i, (name, meal_names, subs, alcoholic) in enumerate(CATEGORIES):
        cat = MenuCategory(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name,
            sort_order=i,
            is_alcoholic=alcoholic,
            is_active=not alcoholic,
        )
        session.add(cat)
        await session.flush()
        for m in meal_names:
            session.add(CategoryMealType(tenant_id=tenant_id, category_id=cat.id, meal_type_id=meals[m].id))
        for j, sub in enumerate(subs):
            session.add(MenuSubcategory(tenant_id=tenant_id, category_id=cat.id, name=sub, sort_order=j))
    await session.flush()

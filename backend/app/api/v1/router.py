"""Aggregates every v1 module router. New modules are added here phase by phase."""

from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.bookings.router import router as bookings_router
from app.api.v1.health.router import router as health_router
from app.api.v1.orders.router import router as orders_router
from app.api.v1.public.router import router as public_router
from app.api.v1.restaurant.bookings_router import router as restaurant_bookings_router
from app.api.v1.restaurant.inventory_router import router as restaurant_inventory_router
from app.api.v1.restaurant.menu_router import router as restaurant_menu_router
from app.api.v1.restaurant.orders_router import router as restaurant_orders_router
from app.api.v1.restaurant.profile_router import router as restaurant_profile_router
from app.api.v1.restaurant.router import router as restaurant_router
from app.api.v1.restaurant.staff_router import router as restaurant_ops_router
from app.api.v1.super_admin.router import router as super_admin_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(public_router)
api_router.include_router(restaurant_router)
api_router.include_router(restaurant_profile_router)
api_router.include_router(restaurant_menu_router)
api_router.include_router(restaurant_ops_router)
api_router.include_router(restaurant_bookings_router)
api_router.include_router(bookings_router)
api_router.include_router(restaurant_orders_router)
api_router.include_router(restaurant_inventory_router)
api_router.include_router(orders_router)
api_router.include_router(super_admin_router)

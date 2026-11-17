"""Import every model module here so Alembic autogenerate sees all tables."""

from app.models.base import Base
from app.models.booking import QueueEntry, Reservation, ReservationPayment, ReservationPolicy, ReservationTable
from app.models.identity import OtpChallenge, RefreshToken, User
from app.models.menu import (
    CategoryMealType,
    MealType,
    MenuAddon,
    MenuAddonGroup,
    MenuCategory,
    MenuItem,
    MenuItemAvailability,
    MenuItemBranchOverride,
    MenuItemVariant,
    MenuSubcategory,
)
from app.models.orders import Order, OrderItem, OrderStatusHistory
from app.models.platform import AuditLog, IdempotencyKey, OutboxEvent
from app.models.profile import BusinessHours, GalleryImage, MediaFile, RestaurantBranding, RestaurantProfile, SocialLink
from app.models.saas import Plan, PlanFeature, Subscription
from app.models.support import SupportTicket
from app.models.tables import RestaurantTable, TableAssignment, TableSection, TableSession
from app.models.tenancy import Branch, Membership, Permission, Role, RolePermission, Tenant, UserBranch

__all__ = [
    "AuditLog",
    "Base",
    "Branch",
    "QueueEntry",
    "Reservation",
    "ReservationPayment",
    "ReservationPolicy",
    "ReservationTable",
    "CategoryMealType",
    "BusinessHours",
    "GalleryImage",
    "IdempotencyKey",
    "MealType",
    "MenuCategory",
    "MenuItem",
    "MenuSubcategory",
    "MenuAddon",
    "MenuAddonGroup",
    "MenuItemAvailability",
    "MenuItemBranchOverride",
    "MenuItemVariant",
    "Order",
    "OrderItem",
    "OrderStatusHistory",
    "MediaFile",
    "RestaurantBranding",
    "RestaurantProfile",
    "SocialLink",
    "SupportTicket",
    "RestaurantTable",
    "TableAssignment",
    "TableSection",
    "TableSession",
    "Membership",
    "OtpChallenge",
    "OutboxEvent",
    "Permission",
    "Plan",
    "PlanFeature",
    "RefreshToken",
    "Role",
    "RolePermission",
    "Subscription",
    "Tenant",
    "User",
    "UserBranch",
]

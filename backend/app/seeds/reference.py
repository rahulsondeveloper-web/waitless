"""Reference data: permission keys, system roles and default plans (docs/04-roles-permissions.md).

Synced idempotently by `python -m app.cli seed`. Editing these lists and re-running seed updates the
database; plan prices/features changed later by the Super Admin in the UI are NOT overwritten
(plans are only inserted if missing).
"""

ALL = "all"
OWN = "own_branches"  # "B" in the permission matrix

PERMISSIONS: dict[str, tuple[str, str]] = {
    # key: (module, description)
    "restaurant.profile.manage": ("restaurant", "Edit restaurant profile, hours and contacts"),
    "restaurant.profile.view": ("restaurant", "View restaurant profile"),
    "restaurant.branding.manage": ("restaurant", "Change logo, colours and theme"),
    "restaurant.gallery.manage": ("restaurant", "Manage gallery photos"),
    "branches.manage": ("branches", "Create and edit branches"),
    "branches.view": ("branches", "View branches"),
    "staff.manage": ("staff", "Invite and manage employees and roles"),
    "tables.configure": ("tables", "Create and edit tables and sections"),
    "tables.operate": ("tables", "Assign, transfer and release tables"),
    "queue.manage": ("queue", "Manage the walk-in queue"),
    "reservations.view": ("reservations", "View reservations"),
    "reservations.manage": ("reservations", "Confirm arrival, cancel, mark no-show"),
    "reservations.policy.manage": ("reservations", "Edit reservation policies and fees"),
    "menu.manage": ("menu", "Manage menu, categories and items"),
    "menu.availability.toggle": ("menu", "Mark items out of stock for today"),
    "orders.create": ("orders", "Place orders for a table"),
    "orders.view": ("orders", "View orders"),
    "orders.cancel": ("orders", "Cancel orders"),
    "orders.mark_served": ("orders", "Mark orders as served"),
    "kitchen.operate": ("kitchen", "Accept and progress kitchen tickets"),
    "billing.operate": ("billing", "Generate, split, merge and close bills"),
    "billing.discount.apply": ("billing", "Apply manual discounts"),
    "payments.collect": ("payments", "Collect payments"),
    "payments.refund": ("payments", "Issue refunds"),
    "discounts.policy.manage": ("discounts", "Edit the serving-time discount policy"),
    "inventory.view": ("inventory", "View stock"),
    "inventory.adjust": ("inventory", "Record wastage, damage and adjustments"),
    "inventory.transfer": ("inventory", "Transfer stock between branches"),
    "suppliers.manage": ("inventory", "Manage suppliers"),
    "purchases.manage": ("inventory", "Manage purchase orders"),
    "recipes.manage": ("inventory", "Map menu items to ingredients"),
    "reports.view": ("reports", "View reports"),
    "reports.sales.view": ("reports", "View sales reports"),
    "settings.manage": ("settings", "Edit restaurant settings"),
    "subscription.manage": ("subscription", "View plan, upgrade, pay WaitLess invoices"),
}

# role key -> (name, description, {permission: scope})
SYSTEM_ROLES: dict[str, tuple[str, str, dict[str, str]]] = {
    "owner": (
        "Owner",
        "Full control of the restaurant",
        {key: ALL for key in PERMISSIONS},
    ),
    "manager": (
        "Manager",
        "Day-to-day operations of assigned branches",
        {
            "restaurant.profile.view": ALL,
            "restaurant.gallery.manage": ALL,
            "branches.view": ALL,
            "staff.manage": OWN,
            "tables.configure": OWN,
            "tables.operate": OWN,
            "queue.manage": OWN,
            "reservations.view": OWN,
            "reservations.manage": OWN,
            "menu.manage": ALL,
            "menu.availability.toggle": OWN,
            "orders.create": OWN,
            "orders.view": OWN,
            "orders.cancel": OWN,
            "orders.mark_served": OWN,
            "kitchen.operate": OWN,
            "billing.operate": OWN,
            "billing.discount.apply": OWN,
            "payments.collect": OWN,
            "payments.refund": OWN,
            "inventory.view": OWN,
            "inventory.adjust": OWN,
            "inventory.transfer": OWN,
            "suppliers.manage": ALL,
            "purchases.manage": OWN,
            "recipes.manage": ALL,
            "reports.view": OWN,
            "reports.sales.view": OWN,
        },
    ),
    "cashier": (
        "Cashier",
        "Billing and payments",
        {
            "reservations.view": OWN,
            "orders.create": OWN,
            "orders.view": OWN,
            "billing.operate": OWN,
            "payments.collect": OWN,
            "reports.sales.view": OWN,
        },
    ),
    "waiter": (
        "Waiter",
        "Tables, queue, orders and serving",
        {
            "tables.operate": OWN,
            "queue.manage": OWN,
            "reservations.view": OWN,
            "reservations.manage": OWN,
            "orders.create": OWN,
            "orders.view": OWN,
            "orders.mark_served": OWN,
        },
    ),
    "kitchen": (
        "Kitchen Staff",
        "Kitchen display",
        {
            "menu.availability.toggle": OWN,
            "orders.view": OWN,
            "kitchen.operate": OWN,
            "inventory.view": OWN,
        },
    ),
}

# Feature keys and limits per plan (docs/04 §4). None = unlimited.
_COMMON = {"storefront": None, "menu.basic": None, "queue": None, "tables": None}
_PRO = {
    **_COMMON,
    "reservations": None,
    "reservations.paid": None,
    "ordering": None,
    "inventory": None,
    "billing_pos": None,
    "analytics.basic": None,
}

PLANS: list[dict] = [
    {
        "code": "starter",
        "name": "Starter",
        "description": "Storefront, menu, queue and table management for a single outlet.",
        "price_monthly": "0.00",
        "price_yearly": "0.00",
        "trial_days": 14,
        "sort_order": 1,
        "features": {**_COMMON, "max_branches": 1, "max_staff": 10, "max_tables_per_branch": 20},
    },
    {
        "code": "professional",
        "name": "Professional",
        "description": "Reservations, digital ordering with the 15-minute promise, inventory, billing and analytics.",
        "price_monthly": "0.00",
        "price_yearly": "0.00",
        "trial_days": 14,
        "sort_order": 2,
        "features": {**_PRO, "max_branches": 5, "max_staff": 50, "max_tables_per_branch": 100},
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "description": "Unlimited scale, advanced analytics, WhatsApp notifications and priority support.",
        "price_monthly": "0.00",
        "price_yearly": "0.00",
        "trial_days": 14,
        "sort_order": 3,
        "features": {
            **_PRO,
            "analytics.advanced": None,
            "notifications.whatsapp": None,
            "priority_support": None,
            "custom_integrations": None,
            "max_branches": None,
            "max_staff": None,
            "max_tables_per_branch": None,
        },
    },
]

# Default restaurant settings created at registration (PRD §4 step 6).
DEFAULT_TENANT_SETTINGS: dict = {
    "currency": "INR",
    "timezone": "Asia/Kolkata",
    "service_charge_pct": "0.00",
    "prices_include_tax": False,
    "manager_limits": {"manual_discount_pct": "10.00", "refund_amount": "2000.00"},
    "serving_promise": {
        "serving_minutes": 15,
        "initial_pct": "2.00",
        "interval_minutes": 5,
        "increment_pct": "2.00",
        "max_pct": "20.00",
    },
}

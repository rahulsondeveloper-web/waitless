# 02 — Database ER Diagram

PostgreSQL 18, schema `public`, migrations via Alembic. Diagrams are split by module; only key columns are shown. Full column definitions are written in the Alembic migrations of each phase.

## Conventions (apply to every table)

| Rule | Detail |
|---|---|
| Primary key | `id uuid DEFAULT uuidv7()` |
| Tenant-owned tables | `tenant_id uuid NOT NULL` + `UNIQUE (tenant_id, id)`; branch-owned tables also `branch_id uuid NOT NULL` |
| Foreign keys between tenant tables | Composite: `FOREIGN KEY (tenant_id, x_id) REFERENCES x (tenant_id, id)` — blocks cross-tenant links |
| RLS | Enabled on every table that has `tenant_id` |
| Timestamps | `created_at`, `updated_at timestamptz NOT NULL DEFAULT now()`; all UTC |
| Soft delete | `archived_at timestamptz NULL` where history must survive (menu items, tables, employees) |
| Money | `NUMERIC(12,2)`, `CHECK (>= 0)`; percentages `NUMERIC(5,2) CHECK (BETWEEN 0 AND 100)` |
| Quantities (inventory) | `NUMERIC(14,3)` in the item's base unit |
| Enums | PostgreSQL `text` + `CHECK (... IN (...))` (easier to evolve than native enums) |
| Snapshots | Orders, bills and invoices copy names, prices, tax rates and policies at the time of the transaction |

Legend: `PK` primary key, `FK` foreign key, `UK` unique.

---

## 1. Platform, identity & SaaS

```mermaid
erDiagram
  TENANTS ||--o{ BRANCHES : has
  TENANTS ||--o{ MEMBERSHIPS : employs
  USERS ||--o{ MEMBERSHIPS : "belongs via"
  ROLES ||--o{ MEMBERSHIPS : grants
  MEMBERSHIPS ||--o{ USER_BRANCHES : "scoped to"
  BRANCHES ||--o{ USER_BRANCHES : includes
  ROLES ||--o{ ROLE_PERMISSIONS : has
  PERMISSIONS ||--o{ ROLE_PERMISSIONS : in
  USERS ||--o{ REFRESH_TOKENS : owns
  USERS ||--o{ OTP_CHALLENGES : requests
  PLANS ||--o{ PLAN_FEATURES : defines
  PLANS ||--o{ SUBSCRIPTIONS : "subscribed as"
  TENANTS ||--o{ SUBSCRIPTIONS : holds
  SUBSCRIPTIONS ||--o{ SAAS_INVOICES : bills
  SAAS_INVOICES ||--o{ SAAS_PAYMENTS : "paid by"
  TENANTS ||--o{ AUDIT_LOGS : "subject of"
  TENANTS ||--o{ SUPPORT_TICKETS : raises

  TENANTS {
    uuid id PK
    text name
    text slug UK
    text status "pending|active|suspended|deactivated|rejected"
    bool is_published
    bool alcohol_licensed
    timestamptz approved_at
  }
  BRANCHES {
    uuid id PK
    uuid tenant_id FK
    text name
    text address
    numeric lat
    numeric lng
    text timezone
    bool is_primary
  }
  USERS {
    uuid id PK
    text phone UK
    text email UK
    text password_hash "null for OTP-only customers"
    text full_name
    bool is_super_admin
    bool phone_verified
  }
  ROLES {
    uuid id PK
    uuid tenant_id "null = system role"
    text key
    text name
  }
  PERMISSIONS {
    text key PK "e.g. orders.manage"
    text module
  }
  MEMBERSHIPS {
    uuid id PK
    uuid tenant_id FK
    uuid user_id FK
    uuid role_id FK
    text status
  }
  USER_BRANCHES {
    uuid membership_id FK
    uuid branch_id FK
  }
  PLANS {
    uuid id PK
    text code UK
    numeric price_monthly
    numeric price_yearly
    bool is_public
  }
  PLAN_FEATURES {
    uuid plan_id FK
    text feature_key "e.g. inventory, max_branches"
    bool enabled
    int limit_value "null = unlimited"
  }
  SUBSCRIPTIONS {
    uuid id PK
    uuid tenant_id FK
    uuid plan_id FK
    text status "trialing|active|past_due|cancelled|expired"
    timestamptz current_period_end
  }
  SAAS_INVOICES {
    uuid id PK
    uuid tenant_id FK
    text number UK
    numeric total
    text status
  }
  AUDIT_LOGS {
    uuid id PK
    uuid tenant_id "nullable"
    uuid actor_user_id
    text action
    text entity
    jsonb diff
  }
```

Also in this group (not drawn): `refresh_tokens` (family id, hash, revoked_at), `otp_challenges`, `idempotency_keys`, `outbox_events`, `platform_settings`, `platform_content` (landing-page CMS blocks), `support_tickets`, `support_notes`, `alcohol_licences`.

**Key constraints**
- `memberships UNIQUE (tenant_id, user_id)` — one role per user per restaurant.
- `subscriptions`: partial unique index `ON (tenant_id) WHERE status IN ('trialing','active','past_due')` — one live subscription per tenant.
- **Restaurant billing tables never reference SaaS billing tables and vice versa** (PRD §9).

---

## 2. Restaurant profile & branding

```mermaid
erDiagram
  TENANTS ||--|| RESTAURANT_PROFILES : describes
  TENANTS ||--|| RESTAURANT_BRANDING : themes
  TENANTS ||--o{ RESTAURANT_GALLERY : shows
  BRANCHES ||--o{ RESTAURANT_BUSINESS_HOURS : opens
  TENANTS ||--o{ RESTAURANT_SOCIAL_LINKS : links
  TENANTS ||--o{ MEDIA_FILES : stores

  RESTAURANT_PROFILES {
    uuid tenant_id PK
    text short_description
    text description
    text about_us
    text restaurant_type
    text_array cuisines
    text phone
    text email
    text website
    uuid cover_media_id FK
  }
  RESTAURANT_BRANDING {
    uuid tenant_id PK
    uuid logo_media_id FK
    jsonb tokens "primary, secondary, accent, ..."
    text button_style "pill|rounded|square"
    text mode "light|dark|auto"
    int version
  }
  RESTAURANT_GALLERY {
    uuid id PK
    uuid tenant_id FK
    uuid media_id FK
    smallint position "1..5"
    text caption
    bool is_active
  }
  RESTAURANT_BUSINESS_HOURS {
    uuid id PK
    uuid branch_id FK
    smallint weekday "0..6"
    time opens_at
    time closes_at
    bool is_closed
  }
  MEDIA_FILES {
    uuid id PK
    uuid tenant_id FK
    text storage_key
    text mime
    int width
    int height
    int bytes
  }
```

**Key constraints**
- Gallery: `UNIQUE (tenant_id, position) WHERE is_active` and `CHECK (position BETWEEN 1 AND 5)` → at most five active photos, enforced by the database. The service also checks the platform setting `gallery_max_photos` so the limit can change via config + migration.
- Branding `tokens` validated by Pydantic (hex colours, WCAG contrast warning in the UI). "Reset to default" writes the default token set and bumps `version`.

---

## 3. Tables, queue & reservations

```mermaid
erDiagram
  BRANCHES ||--o{ TABLE_SECTIONS : has
  TABLE_SECTIONS ||--o{ RESTAURANT_TABLES : contains
  RESTAURANT_TABLES ||--o{ TABLE_ASSIGNMENTS : "assigned in"
  TABLE_SESSIONS ||--o{ TABLE_ASSIGNMENTS : uses
  BRANCHES ||--o{ QUEUE_SESSIONS : "runs daily"
  QUEUE_SESSIONS ||--o{ QUEUE_ENTRIES : holds
  QUEUE_ENTRIES |o--o| TABLE_SESSIONS : "seated as"
  BRANCHES ||--o{ RESERVATION_POLICIES : configures
  RESERVATIONS ||--o{ RESERVATION_TABLES : holds
  RESTAURANT_TABLES ||--o{ RESERVATION_TABLES : "booked as"
  RESERVATIONS ||--o{ RESERVATION_PAYMENTS : "paid by"
  RESERVATIONS |o--o| TABLE_SESSIONS : "checked in as"
  USERS ||--o{ RESERVATIONS : makes

  RESTAURANT_TABLES {
    uuid id PK
    uuid tenant_id FK
    uuid branch_id FK
    text label
    smallint capacity
    text status "available|reserved|occupied|cleaning"
    bool is_active
  }
  TABLE_SESSIONS {
    uuid id PK
    uuid tenant_id FK
    uuid branch_id FK
    text public_code UK "e.g. UB-4821"
    text pin_hash
    text source "walk_in|queue|reservation"
    text status "open|finished|closed"
    smallint party_size
    timestamptz opened_at
    timestamptz closed_at
  }
  TABLE_ASSIGNMENTS {
    uuid id PK
    uuid table_id FK
    uuid table_session_id FK
    timestamptz assigned_at
    timestamptz released_at
  }
  QUEUE_ENTRIES {
    uuid id PK
    uuid queue_session_id FK
    text token "A-017"
    smallint party_size
    text phone
    text status "waiting|notified|seated|cancelled|no_show|skipped"
    int position
    timestamptz joined_at
  }
  RESERVATIONS {
    uuid id PK
    uuid tenant_id FK
    uuid branch_id FK
    uuid customer_id FK
    text type "free|paid"
    text status "pending_payment|confirmed|checked_in|completed|expired|cancelled|no_show"
    smallint party_size
    tstzrange slot
    timestamptz arrival_window_end
    timestamptz staff_confirmed_at
    jsonb policy_snapshot
  }
  RESERVATION_PAYMENTS {
    uuid id PK
    uuid reservation_id FK
    numeric amount
    text gateway_payment_id UK
    text status
  }
```

**Key constraints**
- No double assignment: `UNIQUE (table_id) WHERE released_at IS NULL` on `table_assignments`.
- No overlapping bookings: `reservation_tables` carries `slot tstzrange` and `EXCLUDE USING gist (table_id WITH =, slot WITH &&) WHERE (active)` (needs `btree_gist`).
- Expiry job only updates rows `WHERE status = 'confirmed' AND staff_confirmed_at IS NULL` — a checked-in reservation can never be expired.
- `public_code` is unique among **open** sessions per tenant: `UNIQUE (tenant_id, public_code) WHERE status <> 'closed'`.

---

## 4. Menu

```mermaid
erDiagram
  TENANTS ||--o{ MENU_MEAL_TYPES : defines
  MENU_MEAL_TYPES ||--o{ MENU_CATEGORIES : groups
  MENU_CATEGORIES ||--o{ MENU_SUBCATEGORIES : splits
  MENU_CATEGORIES ||--o{ MENU_ITEMS : lists
  MENU_SUBCATEGORIES |o--o{ MENU_ITEMS : lists
  MENU_ITEMS ||--o{ MENU_ITEM_VARIANTS : "sized as"
  MENU_ITEMS ||--o{ MENU_ITEM_ADDON_GROUPS : offers
  MENU_ITEM_ADDON_GROUPS ||--o{ MENU_ITEM_ADDONS : contains
  MENU_ITEMS ||--o{ MENU_ITEM_AVAILABILITY : "available when"
  MENU_ITEMS ||--o{ MENU_ITEM_BRANCH_OVERRIDES : "per branch"
  MENU_ITEMS }o--o{ MENU_ITEM_TAGS : tagged
  TAX_RATES ||--o{ MENU_ITEMS : taxes

  MENU_CATEGORIES {
    uuid id PK
    uuid tenant_id FK
    uuid meal_type_id FK
    text name
    bool is_alcoholic
    int sort_order
    bool is_active
  }
  MENU_ITEMS {
    uuid id PK
    uuid tenant_id FK
    uuid category_id FK
    text name
    text description
    uuid image_media_id FK
    numeric base_price
    text food_class "veg|non_veg|egg|vegan|jain"
    smallint spice_level "0..3"
    text_array allergens
    smallint prep_minutes
    uuid tax_rate_id FK
    bool is_bestseller
    bool is_todays_special
    timestamptz archived_at
  }
  MENU_ITEM_VARIANTS {
    uuid id PK
    uuid item_id FK
    text name "Half / Full"
    numeric price
  }
  MENU_ITEM_ADDONS {
    uuid id PK
    uuid group_id FK
    text name
    numeric price
  }
  MENU_ITEM_AVAILABILITY {
    uuid id PK
    uuid item_id FK
    smallint weekday
    time from_time
    time to_time
  }
  MENU_ITEM_BRANCH_OVERRIDES {
    uuid item_id FK
    uuid branch_id FK
    numeric price_override
    bool is_available
    bool out_of_stock
  }
```

**Key constraints**
- Alcohol: a trigger/service check refuses activating `is_alcoholic` categories unless `tenants.alcohol_licensed = true`.
- Default meal types and categories (PRD §7.1–7.2) are **seeded per tenant on registration** and remain editable.
- `MENU_ITEM_TAGS` is many-to-many through `menu_item_tag_links`.

---

## 5. Orders, kitchen, SLA & discounts

```mermaid
erDiagram
  TABLE_SESSIONS ||--o{ ORDERS : contains
  RESERVATIONS |o--o{ ORDERS : "pre-ordered"
  ORDERS ||--o{ ORDER_ITEMS : lines
  ORDER_ITEMS ||--o{ ORDER_ITEM_ADDONS : extras
  ORDERS ||--o{ ORDER_STATUS_HISTORY : logs
  ORDERS ||--o{ KITCHEN_ORDER_EVENTS : tracks
  ORDERS ||--o| ORDER_SLA : timed
  DISCOUNT_POLICIES ||--o{ ORDER_SLA : "snapshotted into"
  ORDERS ||--o{ ORDER_DISCOUNTS : receives

  ORDERS {
    uuid id PK
    uuid tenant_id FK
    uuid branch_id FK
    uuid table_session_id FK
    uuid reservation_id FK
    text number "per-branch sequence"
    text order_type "walk_in|free_booking|paid_preorder|staff"
    text status "placed|accepted|preparing|ready|served|cancelled"
    numeric subtotal
    numeric tax_total
    text idempotency_key
  }
  ORDER_ITEMS {
    uuid id PK
    uuid order_id FK
    uuid menu_item_id FK
    text name_snapshot
    text variant_snapshot
    numeric unit_price
    numeric tax_rate
    smallint quantity
    text instructions
    text status "pending|preparing|ready|served|cancelled"
  }
  ORDER_SLA {
    uuid order_id PK
    timestamptz sla_started_at
    timestamptz served_at
    jsonb policy_snapshot
    text start_reason "accepted|arrival_confirmed"
    numeric final_discount_pct
  }
  DISCOUNT_POLICIES {
    uuid id PK
    uuid tenant_id FK
    smallint serving_minutes "15"
    numeric initial_pct "2"
    smallint interval_minutes "5"
    numeric increment_pct "2"
    numeric max_pct "20"
    text_array eligible_order_types
    text base "food_subtotal"
    bool is_active
  }
  ORDER_DISCOUNTS {
    uuid id PK
    uuid order_id FK
    text kind "sla_delay|manual|promo"
    numeric pct
    numeric amount
    uuid approved_by
  }
```

**Key constraints**
- `ORDER_SLA.sla_started_at` is set **only** by the server: on `accepted` (walk-in / staff order), on `arrival confirmed + accepted` (free booking), on `staff_confirmed_at` (paid pre-order). Stored once; a `CHECK` + trigger prevents overwriting.
- `UNIQUE (tenant_id, idempotency_key)` on orders prevents duplicate submissions.
- Only one `sla_delay` discount row per order (`UNIQUE (order_id) WHERE kind='sla_delay'`), updated at each boundary until served, then frozen.

---

## 6. Billing & payments (restaurant side)

```mermaid
erDiagram
  TABLE_SESSIONS ||--o{ BILLS : "billed as"
  BILLS ||--o{ BILL_ITEMS : lines
  BILLS ||--o{ PAYMENTS : "settled by"
  PAYMENTS ||--o{ REFUNDS : "reversed by"
  BILLS ||--o| INVOICES : "finalised as"
  RESERVATION_PAYMENTS |o--o{ BILLS : "credited to"

  BILLS {
    uuid id PK
    uuid tenant_id FK
    uuid branch_id FK
    uuid table_session_id FK
    uuid parent_bill_id "for splits"
    text status "open|finalised|paid|void"
    numeric subtotal
    numeric discount_total
    numeric service_charge
    numeric tax_total
    numeric booking_credit
    numeric grand_total
  }
  BILL_ITEMS {
    uuid id PK
    uuid bill_id FK
    uuid order_item_id FK
    numeric amount
  }
  PAYMENTS {
    uuid id PK
    uuid bill_id FK
    text method "cash|upi|card|gateway|other"
    numeric amount
    text gateway_payment_id UK
    text status
  }
  REFUNDS {
    uuid id PK
    uuid payment_id FK
    numeric amount
    text reason
    uuid approved_by
  }
  INVOICES {
    uuid id PK
    uuid bill_id FK
    text number UK "per-tenant series"
    jsonb snapshot "immutable"
    timestamptz issued_at
  }
```

**Key constraints**
- `INVOICES` rows are insert-only (trigger rejects `UPDATE`/`DELETE`). Corrections are **credit notes** (`invoices.kind = 'credit_note'` referencing the original).
- `SUM(payments) - SUM(refunds) <= grand_total` checked in the service inside a `SERIALIZABLE` transaction.
- Webhook processing is idempotent on `gateway_payment_id`.

---

## 7. Inventory

```mermaid
erDiagram
  INVENTORY_CATEGORIES ||--o{ INVENTORY_ITEMS : groups
  INVENTORY_ITEMS ||--o{ INVENTORY_STOCK : "stocked at"
  BRANCHES ||--o{ INVENTORY_STOCK : holds
  INVENTORY_ITEMS ||--o{ INVENTORY_MOVEMENTS : ledger
  SUPPLIERS ||--o{ PURCHASE_ORDERS : supplies
  PURCHASE_ORDERS ||--o{ PURCHASE_ORDER_ITEMS : lines
  INVENTORY_ITEMS ||--o{ PURCHASE_ORDER_ITEMS : bought
  STOCK_TRANSFERS ||--o{ STOCK_TRANSFER_ITEMS : moves
  MENU_ITEMS ||--o| RECIPES : "made by"
  RECIPES ||--o{ RECIPE_INGREDIENTS : needs
  INVENTORY_ITEMS ||--o{ RECIPE_INGREDIENTS : "used in"
  INVENTORY_ADJUSTMENTS ||--o{ INVENTORY_MOVEMENTS : creates

  INVENTORY_ITEMS {
    uuid id PK
    uuid tenant_id FK
    text name
    text sku UK
    text unit "kg|g|l|ml|pcs|pkt|box"
    numeric reorder_level
    numeric min_stock
    bool is_active
  }
  INVENTORY_STOCK {
    uuid item_id FK
    uuid branch_id FK
    numeric on_hand
    numeric reserved
  }
  INVENTORY_MOVEMENTS {
    uuid id PK
    uuid tenant_id FK
    uuid branch_id FK
    uuid item_id FK
    text type "opening|purchase|consumption|reversal|wastage|damage|adjustment|transfer_out|transfer_in|return"
    numeric quantity "signed"
    numeric unit_cost
    text reason
    uuid order_item_id "for consumption"
    uuid actor_user_id
    date expiry_date
  }
  PURCHASE_ORDERS {
    uuid id PK
    uuid supplier_id FK
    text number UK
    text status "draft|ordered|received|cancelled"
    numeric tax_total
    numeric grand_total
    text payment_status
  }
  RECIPE_INGREDIENTS {
    uuid recipe_id FK
    uuid inventory_item_id FK
    numeric quantity
  }
```

**Key constraints**
- The **movement ledger is the truth**; `inventory_stock.on_hand` is a cache maintained in the same transaction (and reconcilable by a report).
- Movements are insert-only; `reason` and `actor_user_id` are `NOT NULL` for adjustments, wastage and damage (PRD §8.2 "never modify stock silently").
- One deduction per order line: `UNIQUE (order_item_id, item_id) WHERE type = 'consumption'`.
- `CHECK (on_hand >= 0)` unless the branch setting `allow_negative_stock` is on.

---

## 8. Notifications

```mermaid
erDiagram
  NOTIFICATION_TEMPLATES ||--o{ NOTIFICATIONS : renders
  USERS ||--o{ NOTIFICATION_PREFERENCES : sets
  NOTIFICATIONS ||--o{ NOTIFICATION_DELIVERY_LOGS : "attempted via"

  NOTIFICATIONS {
    uuid id PK
    uuid tenant_id "nullable for platform"
    uuid recipient_user_id
    text recipient_phone
    text event_key "order.ready"
    jsonb payload
    timestamptz read_at
  }
  NOTIFICATION_DELIVERY_LOGS {
    uuid id PK
    uuid notification_id FK
    text channel "in_app|sms|whatsapp|email|push"
    text status "queued|sent|failed"
    int attempt
    text provider_ref
  }
```

---

## 9. Migration order

Migrations are created phase by phase (see [07-development-plan.md](07-development-plan.md)):

1. Phase 1 — extensions (`btree_gist`, `citext`, `pg_trgm`), roles, `outbox_events`, `idempotency_keys`, `audit_logs`, RLS helper functions.
2. Phase 2 — identity, tenants, branches, roles/permissions, plans, subscriptions.
3. Phase 3 — profile, branding, gallery, hours, media.
4. Phase 5 — tables, sections, sessions, assignments.
5. Phase 6 — queue, reservations.
6. Phase 7 — menu, orders, kitchen.
7. Phase 8 — SLA, discount policies.
8. Phase 9 — inventory.
9. Phase 10 — bills, payments, refunds, invoices.
10. Phase 11 — SaaS invoices/payments, analytics materialised views.

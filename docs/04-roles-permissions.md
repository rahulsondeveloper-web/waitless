# 04 — Roles & Permissions

Three independent checks run on every private request:

1. **Who** — authenticated user and role (RBAC, this document).
2. **Where** — tenant from membership; branch must be in `user_branches` (Owner has all branches).
3. **Plan** — the tenant's subscription enables the feature and its limits are not exceeded (§4).

## 1. Roles

| Role | Scope | Notes |
|---|---|---|
| **Super Admin** | Platform | Full platform control. Access to a tenant's private records requires an explicit "view as" action that is audited. |
| **Platform Support** *(optional)* | Platform | Read-only restaurants, support tickets, notes. Create later if you hire support staff. |
| **Owner** | One tenant, all branches | Created at registration. Cannot be removed by anyone except Super Admin. |
| **Manager** | Tenant, assigned branches | Day-to-day operations, no subscription or branding changes. |
| **Cashier** | Assigned branches | Billing, payments, receipts. |
| **Waiter** | Assigned branches | Tables, queue, take orders, mark served. |
| **Kitchen Staff** | Assigned branches | Kitchen display only. |
| **Custom role** | Tenant | Owner composes from permission keys below. |
| **Customer** | Own records | Verified by phone OTP. |
| **Guest** | Public | Browse public restaurant data, menus, availability. |

## 2. Permission matrix — restaurant side

`✔` full · `R` read only · `B` own branches only · `—` none

| Permission key | Owner | Manager | Cashier | Waiter | Kitchen |
|---|:-:|:-:|:-:|:-:|:-:|
| `restaurant.profile.manage` | ✔ | R | — | — | — |
| `restaurant.branding.manage` | ✔ | — | — | — | — |
| `restaurant.gallery.manage` | ✔ | ✔ | — | — | — |
| `branches.manage` | ✔ | R | — | — | — |
| `staff.manage` | ✔ | B (cannot grant Owner/Manager) | — | — | — |
| `tables.configure` | ✔ | B | — | — | — |
| `tables.operate` (assign, transfer, release, cleaning) | ✔ | B | — | B | — |
| `queue.manage` | ✔ | B | — | B | — |
| `reservations.view` | ✔ | B | B | B | — |
| `reservations.manage` (confirm arrival, cancel, no-show) | ✔ | B | — | B | — |
| `reservations.policy.manage` | ✔ | — | — | — | — |
| `menu.manage` | ✔ | ✔ | — | — | — |
| `menu.availability.toggle` (out of stock today) | ✔ | B | — | — | B |
| `orders.create` (staff order for a table) | ✔ | B | B | B | — |
| `orders.view` | ✔ | B | B | B | B |
| `orders.cancel` | ✔ | B | — | — | — |
| `kitchen.operate` (accept, preparing, ready) | ✔ | B | — | — | B |
| `orders.mark_served` | ✔ | B | — | B | — |
| `billing.operate` (generate, split, merge, close) | ✔ | B | B | — | — |
| `billing.discount.apply` (manual) | ✔ | B (≤ limit) | — | — | — |
| `payments.collect` | ✔ | B | B | — | — |
| `payments.refund` | ✔ | B (≤ limit) | — | — | — |
| `discounts.policy.manage` (SLA policy) | ✔ | — | — | — | — |
| `inventory.view` | ✔ | B | — | — | R |
| `inventory.adjust` (wastage, damage, adjustment) | ✔ | B | — | — | — |
| `inventory.transfer` | ✔ | B | — | — | — |
| `suppliers.manage` | ✔ | ✔ | — | — | — |
| `purchases.manage` | ✔ | B | — | — | — |
| `recipes.manage` | ✔ | ✔ | — | — | — |
| `reports.view` | ✔ | B | R (sales only) | — | — |
| `settings.manage` | ✔ | — | — | — | — |
| `subscription.manage` (view plan, upgrade, pay SaaS invoices) | ✔ | — | — | — | — |

Manager "≤ limit" amounts are configured by the Owner in settings (e.g. manual discount up to 10%, refunds up to ₹2,000).

## 3. Permission matrix — platform & customer side

| Capability | Super Admin | Platform Support | Customer | Guest |
|---|:-:|:-:|:-:|:-:|
| Approve / reject / activate / suspend / deactivate restaurants | ✔ | — | — | — |
| View restaurant list & usage | ✔ | R | — | — |
| View a restaurant's private records ("view as", audited) | ✔ | — | — | — |
| Plans & plan features | ✔ | — | — | — |
| Subscriptions, SaaS invoices, renewals | ✔ | R | — | — |
| Platform analytics | ✔ | R | — | — |
| Landing-page content, terms, privacy | ✔ | — | — | — |
| Support tickets & internal notes | ✔ | ✔ | create own | — |
| Audit logs, system & integration settings | ✔ | — | — | — |
| Approve alcohol licences | ✔ | — | — | — |
| Discover restaurants, view storefront, menu, gallery, availability | ✔ | ✔ | ✔ | ✔ |
| Join queue, reserve table, pay booking fee | — | — | ✔ (verified) | — |
| Pre-order (paid booking only) | — | — | ✔ | — |
| Join table session (code + PIN), order, Finish, pay bill | — | — | ✔ (verified) | — |
| View own bookings, orders, bills, notifications | — | — | ✔ | — |
| Rate a visit (after paid bill) | — | — | ✔ | — |

## 4. Plan feature gates (configurable, PRD §17)

Features and limits live in `plan_features`; Super Admin can create new plans without code. Defaults:

| Feature key | Starter | Professional | Enterprise |
|---|:-:|:-:|:-:|
| `max_branches` | 1 | 5 | unlimited |
| `max_staff` | 10 | 50 | unlimited |
| `max_tables_per_branch` | 20 | 100 | unlimited |
| `storefront` | ✔ | ✔ | ✔ |
| `menu.basic` | ✔ | ✔ | ✔ |
| `queue` | ✔ | ✔ | ✔ |
| `tables` | ✔ | ✔ | ✔ |
| `reservations` | — | ✔ | ✔ |
| `reservations.paid` | — | ✔ | ✔ |
| `ordering` (digital ordering, kitchen display, SLA discounts) | — | ✔ | ✔ |
| `inventory` | — | ✔ | ✔ |
| `billing_pos` | — | ✔ | ✔ |
| `analytics.basic` | — | ✔ | ✔ |
| `analytics.advanced` | — | — | ✔ |
| `notifications.whatsapp` | — | — | ✔ |
| `priority_support` | — | — | ✔ |
| `custom_integrations` | — | — | ✔ |

Enforcement: backend dependency `require_feature("inventory")` returns **402 / `PLAN_FEATURE_REQUIRED`**; limits return **409 / `PLAN_LIMIT_REACHED`**. The admin UI hides or shows an "Upgrade" card using the same feature list from `/api/v1/restaurant/me`.

> Is Starter really meant to exclude ordering? The PRD lists ordering only under Professional. That makes the 15-minute promise (the core product idea) unavailable on Starter. Suggest reconsidering when pricing is set — it is purely configuration.

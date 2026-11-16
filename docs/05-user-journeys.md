# 05 — User Journeys

## 1. Customer journeys

### 1.1 Discover → storefront

```mermaid
flowchart LR
  A["waitless.com"] --> B["Search / filter<br/>name, location, cuisine,<br/>type, open now, wait time"]
  B --> C["Restaurant card<br/>logo, cuisine, wait estimate"]
  C --> D["/r/{slug}<br/>storefront in restaurant branding"]
  D --> E{"What next?"}
  E --> M["View Menu"]
  E --> G["View Gallery<br/>(lightbox, next/prev)"]
  E --> R["Book a Table"]
  E --> Q["Join Queue (at the restaurant)"]
  E --> J["Have an Order ID? Join table"]
  D -->|"WaitLess link in header"| A
```

### 1.2 Walk-in via digital queue (PRD §10)

```mermaid
sequenceDiagram
  actor C as Customer
  participant SF as Storefront
  participant API as Backend
  actor W as Waiter
  C->>SF: Scan QR at entrance → /r/{slug}?branch=..&action=queue
  SF->>C: Party size + phone
  C->>SF: Enter OTP
  SF->>API: POST queue entry
  API-->>SF: Token A-017, position 4, ~18 min
  Note over SF: live updates via socket room queue_entry:{id}
  W->>API: Assign table T5 to A-017
  API-->>C: "Your table is ready" (in-app + SMS)
  W->>API: Mark seated → creates table session UB-4821 + PIN
  API-->>C: Session code shown on phone → continue to ordering (1.5)
```

### 1.3 Free booking (PRD §12)

```mermaid
flowchart TD
  A["Book a Table"] --> B["Branch, date, time, party size"]
  B --> C["Choose: Free booking"]
  C --> D["Verify phone (OTP)"]
  D --> E["Reservation confirmed<br/>(per restaurant policy)"]
  E --> F["Can view menu — cannot pre-order"]
  F --> G{"Arrives within window + grace?"}
  G -->|No| X["Expired → table released,<br/>customer notified"]
  G -->|Yes| H["Staff: Confirm Arrival → table session created"]
  H --> I["Customer orders (app or waiter)"]
  I --> J["Restaurant accepts order → 15-min timer starts"]
```

### 1.4 Paid booking with pre-order (PRD §12, §14)

```mermaid
sequenceDiagram
  actor C as Customer
  participant SF as Storefront
  participant API as Backend
  participant PG as Payment gateway
  actor S as Staff
  C->>SF: Book → Paid booking (fee ₹X)
  SF->>API: POST reservation (pending_payment)
  API->>PG: create order
  C->>PG: pay
  PG-->>API: webhook (signature verified)
  API-->>SF: reservation confirmed
  C->>SF: Build pre-order, see total
  SF->>API: POST pre-order (status placed, NO timer)
  API-->>S: New pre-order notification
  C->>S: Arrives at restaurant
  S->>API: Confirm Arrival
  API->>API: staff_confirmed_at = now() (server UTC)<br/>sla_started_at = staff_confirmed_at
  API-->>C: Timer live: 15:00 remaining
```

### 1.5 Ordering through a table session — "Order ID" flow (PRD §13)

```mermaid
flowchart TD
  A["Waiter opens table / places order for table"] --> B["System creates table session<br/>code UB-4821 + PIN 3927"]
  B --> C["Waiter tells/prints code + PIN for customer"]
  C --> D["Customer: storefront → 'Have an Order ID?'"]
  D --> E["Enter code + PIN (+ phone OTP first time)"]
  E --> F["Session view:<br/>orders, placed time, timer, remaining time,<br/>status, current discount"]
  F --> G["Order more from the app → same session"]
  G --> F
  F --> H["Finish"]
  H --> I["Final invoice: items, SLA discounts,<br/>tax, service charge, booking credit"]
  I --> J{"Pay"}
  J -->|"UPI / card in app"| K["Paid → receipt → rate visit"]
  J -->|"Cash at counter"| L["Cashier records payment"] --> K
```

### 1.6 Serving timer & discount (PRD §14) — what the customer sees

| Minute (since timer start) | Shown |
|---|---|
| 0–15 | Countdown "12:40 left to serve", status chip, discount 0% |
| 15–20 | "Running late — 2% off this order", amount saved |
| 20–25 | 4% … up to the restaurant's max |
| Served | Timer stops; final discount frozen and copied to the bill |

## 2. Restaurant Admin journeys

### 2.1 Onboarding

```mermaid
flowchart LR
  A["Register restaurant<br/>(PRD §4 fields)"] --> B["Tenant + branch + owner +<br/>slug + default settings +<br/>default menu taxonomy"]
  B --> C["Status: pending approval"]
  C --> D["Complete profile:<br/>about, hours, contacts"]
  D --> E["Branding: logo, colours,<br/>live preview, or keep default"]
  E --> F["Gallery: up to 5 photos"]
  F --> G["Tables & sections"]
  G --> H["Menu: categories, items"]
  H --> I["Publish checklist ✔"]
  I --> J{"Super Admin approved?"}
  J -->|Yes| K["Live & discoverable"]
  J -->|No| C
```

Publish checklist (all required to be discoverable): approved + active subscription/trial, logo or name, cover image, address with map pin, opening hours, at least one table, at least one active menu item.

### 2.2 Daily operation (one service)

```mermaid
flowchart TD
  O["Open dashboard<br/>today's KPIs"] --> Q["Queue board<br/>assign tables"]
  O --> R["Reservations<br/>confirm arrivals"]
  O --> T["Table map<br/>green/yellow/red/blue"]
  Q & R & T --> S["Table session open"]
  S --> K["Kitchen display<br/>accept → preparing → ready"]
  K --> W["Waiter marks served"]
  W --> B["Bill: split/merge,<br/>collect payment"]
  B --> C["Close session → table to Cleaning → Available"]
  O --> I["Low-stock alerts → purchase order"]
```

### 2.3 Back-office

| Area | Main tasks |
|---|---|
| Menu | Meal types, categories, sub-categories, items, variants, add-ons, availability windows, bestseller / today's special |
| Inventory | Opening stock, purchases, wastage/damage with reason, transfers between branches, recipe mapping |
| Discounts | SLA policy (serving minutes, initial, interval, increment, max, eligible order types) |
| Staff | Invite employee (phone/email), assign role & branches, deactivate |
| Reports | Sales, orders, serving time & delays, discounts given, inventory valuation & wastage |
| Subscription | Current plan, usage vs limits, upgrade, pay SaaS invoice |

## 3. Super Admin journeys

```mermaid
flowchart TD
  L["Login (super admin, 2FA later)"] --> O["Platform overview<br/>restaurants, orders, SaaS revenue"]
  O --> RQ["Pending registrations"]
  RQ --> V["Review details + licence"]
  V -->|Approve| AC["Activate → trial / assign plan"]
  V -->|Reject| RJ["Reject with reason → owner notified"]
  O --> RM["Restaurant management<br/>edit, suspend, deactivate, view usage"]
  RM --> VA["View as restaurant (audited, read-only by default)"]
  O --> PL["Plans: create/edit, features, limits, prices"]
  PL --> SB["Subscriptions: assign, upgrade, downgrade,<br/>renewals, expired list"]
  O --> CM["Content: landing sections, about,<br/>how it works, terms, privacy"]
  O --> SP["Support: tickets, complaints, notes"]
  O --> AU["Audit logs, admin activity,<br/>system & integration settings"]
```

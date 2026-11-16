# WAITLESS
## Complete Product Requirements Document (PRD) and Master Development Prompt

**Product Name:** WaitLess  
**Tagline:** Skip the Wait. Dine Delightfully!  
**Product Type:** Multi-Tenant Restaurant SaaS Platform  
**Platform Owner:** WaitLess Super Admin  
**Frontend:** Angular 20+  
**Backend:** Python FastAPI  
**Database:** PostgreSQL  
**Cache and Real-Time Infrastructure:** Redis + Socket.IO

---

# 1. PROJECT VISION

Develop WaitLess as a complete, modern, scalable and production-ready SaaS platform for restaurants.

WaitLess should provide restaurants with their own digitally branded customer-facing application while allowing the platform owner to manage all restaurants through one centralized Super Admin dashboard.

The platform should combine:

- Restaurant discovery.
- Restaurant-branded websites and digital storefronts.
- Table reservations.
- Digital queue management.
- Table management.
- Digital menus.
- Advance food ordering.
- Kitchen management.
- Inventory management.
- Billing and payments.
- Automatic food-serving delay discounts.
- Restaurant analytics.
- SaaS subscription management.

The most important product requirement is that each restaurant should have its own identity and branding when customers interact with it.

WaitLess should work as both:
1. A restaurant discovery and SaaS platform.
2. A dynamic restaurant-specific customer application.

---

# 2. CORE APPLICATION CONCEPT: DYNAMIC RESTAURANT BRANDING

This is one of the most important architectural requirements.

The application must support a central WaitLess platform and multiple independently branded restaurant experiences using the same Angular frontend and FastAPI backend.

## 2.1 WaitLess Main Landing Page

When a customer searches for WaitLess and visits the website, the customer should see the main WaitLess landing page.

Example:

`www.waitless.com`

The landing page should display WaitLess branding.

### Landing page sections

- WaitLess logo.
- Header navigation.
- Home.
- About Us.
- How It Works.
- Features.
- For Restaurants.
- Benefits for Restaurant Owners.
- Contact Us.
- Restaurant Discovery.
- Login / Register.

### About Us

Explain the business and its purpose.

WaitLess helps restaurants digitize their operations and helps customers avoid unnecessary waiting.

Describe:
- Our vision.
- Our mission.
- How WaitLess works.
- Benefits for customers.
- Benefits for restaurants.
- Restaurant technology solutions.
- Digital ordering and queue management.
- Restaurant SaaS solutions.

### Restaurant Discovery

Customers should be able to search and discover restaurants registered on WaitLess.

Search filters may include:
- Restaurant name.
- Location.
- Cuisine.
- Restaurant type.
- Availability.
- Waiting time.

When a customer selects a restaurant, navigate to that restaurant's branded experience.

---

## 2.2 Restaurant-Specific Application

Example restaurant:

**Urban Bites**

Restaurant URL:

`www.waitless.com/r/urban-bites`

The application must dynamically load the selected restaurant's information using its unique slug.

When the customer visits this URL, the customer-facing interface should display:

- Urban Bites logo.
- Urban Bites restaurant name.
- Restaurant cover image.
- Restaurant information.
- Restaurant gallery.
- Restaurant menu.
- Restaurant availability.
- Table reservations.
- Digital ordering.
- Customer account and booking information.

The entire customer-facing experience should look like the restaurant's own application.

The customer should not feel that they are using a generic restaurant application.

### Header Design

The restaurant-specific header should contain:

**Left side:**
- Restaurant logo.
- Restaurant name.

**Navigation:**
- Home.
- Menu.
- Gallery.
- About Us.
- Reservations.
- Contact.

**Right side:**
- Login / Profile.
- Cart.
- WaitLess branding/link.

The WaitLess option must always be visible on the right side of the header.

When the customer clicks WaitLess:

- Navigate to the main WaitLess landing page.
- Restore WaitLess branding.
- Display the main platform's About Us and business information.

Do not remove this WaitLess navigation option from restaurant pages.

### Restaurant Theme

Each restaurant should be able to configure:
- Primary color.
- Secondary color.
- Accent color.
- Logo.
- Cover image.

Use restaurant branding dynamically.

The theme must update without requiring a new Angular build or deployment.

### Dynamic Data Loading

When the customer navigates to a restaurant:

1. Read the restaurant slug from the route.
2. Call the public restaurant API.
3. Fetch the restaurant profile.
4. Fetch its branding and theme.
5. Fetch its gallery images.
6. Fetch its available menu.
7. Fetch its branches and public availability.
8. Load the restaurant-specific customer experience.

When the customer navigates from Restaurant A to Restaurant B, all restaurant-specific data must be replaced.

Never display Restaurant A's:
- Logo.
- Menu.
- Gallery.
- Contact information.
- Availability.
- Orders or reservation details.

on Restaurant B's storefront.

Use reusable Angular components with tenant-aware data services.

Do not create a separate Angular application for every restaurant.

---

# 3. APPLICATION USERS AND ACCESS LEVELS

There are three main application experiences.

## 3.1 WaitLess Super Admin – Platform Owner

I will be the owner and Super Admin of the complete WaitLess platform.

The Super Admin should have complete platform-level control.

Responsibilities:

- Manage all restaurants.
- Approve or reject restaurant registrations.
- Activate or deactivate restaurants.
- Suspend restaurants.
- Manage restaurant subscriptions.
- Manage subscription plans.
- Manage SaaS billing.
- View platform-wide analytics.
- Manage platform configuration.
- Manage support requests.
- Manage platform content.
- Manage WaitLess landing page content.

Super Admin must be able to access all restaurant records when authorized, but platform-wide access must be controlled and audited.

## 3.2 Restaurant Owner – Restaurant Admin

Each restaurant owner receives an independent admin account.

After login, the owner can access only their restaurant's authorized data.

The owner can manage:

- Restaurant profile.
- Restaurant branding.
- Restaurant logo.
- Restaurant photos.
- Restaurant information.
- Branches.
- Employees.
- Tables.
- Reservations.
- Queue.
- Menus.
- Food items.
- Inventory.
- Orders.
- Kitchen.
- Billing.
- Payments.
- Discount policies.
- Reports and analytics.

A restaurant owner must never be able to access another restaurant's private information.

## 3.3 Customer

Customers can:

- Discover restaurants.
- Visit restaurant-branded storefronts.
- View restaurant information.
- View gallery photos.
- Browse menus.
- Check availability.
- Reserve tables.
- Join queues.
- Pre-order food when eligible.
- Track orders.
- Receive discounts.
- View bills.
- Make payments.

Allow guest browsing of public restaurant information.

Require appropriate customer verification before sensitive booking, payment or account operations.

---

# 4. RESTAURANT REGISTRATION AND ONBOARDING

Build a restaurant registration process.

A restaurant owner should be able to register their restaurant on WaitLess.

Initial information:

- Restaurant name.
- Owner name.
- Email.
- Mobile number.
- Password.
- Restaurant address.
- City.
- State.
- Country.
- Cuisine.
- Restaurant type.
- Number of branches.

After registration:

1. Create a tenant record.
2. Create the initial branch.
3. Create the restaurant owner account.
4. Assign the Restaurant Admin role.
5. Create the restaurant's unique slug.
6. Initialize default restaurant settings.
7. Allow the owner to complete the restaurant profile.

Super Admin can approve and activate the restaurant.

The restaurant should not become publicly discoverable until its publication and activation requirements are satisfied.

---

# 5. RESTAURANT PROFILE AND BRANDING MANAGEMENT

Create a dedicated Restaurant Profile Management module.

Restaurant owners must be able to manage all information displayed on their public restaurant storefront.

## 5.1 Restaurant Basic Information

- Restaurant name.
- Unique restaurant slug.
- Short description.
- Detailed description.
- About Us.
- Restaurant type.
- Cuisine types.
- Contact number.
- Email.
- Website.
- Address.
- Google Maps location.
- Opening hours.
- Weekly closing days.
- Social media links.

## 5.2 Restaurant Logo

Allow the owner to:

- Upload a logo.
- Preview the logo.
- Replace the logo.
- Remove the logo.
- Crop or resize the logo if required.

The logo must automatically appear in the restaurant's customer-facing header.

## 5.3 Restaurant Gallery – Maximum Five Photos

Allow restaurant owners to upload up to five restaurant photos.

These photos should be displayed in a Gallery section on the restaurant storefront.

Requirements:

- Maximum five active gallery photos.
- Image preview.
- Image replacement.
- Image deletion.
- Reordering.
- Upload validation.
- Image optimization.
- Responsive gallery display.

Add a **View Gallery** option on the restaurant homepage.

When customers click View Gallery:

- Open a dedicated gallery page or modal.
- Display all uploaded restaurant photos.
- Support image enlargement.
- Support next/previous navigation.
- Display images in an attractive responsive layout.

Do not allow more than five active gallery photos per restaurant unless the platform configuration is changed.

## 5.4 Restaurant Theme Configuration

Allow restaurant owners to configure:

- Primary color.
- Secondary color.
- Accent color.
- Button style where appropriate.
- Light/dark theme preference where supported.

Provide a live preview before saving.

The customer-facing application must apply these settings dynamically.

---

# 6. RESTAURANT CUSTOMER STOREFRONT

Each restaurant should have a reusable customer-facing storefront.

Suggested URL:

`www.waitless.com/r/{restaurant-slug}`

Create the following sections:

1. Home.
2. About Us.
3. Menu.
4. Gallery.
5. Reservations.
6. Availability.
7. Contact Us.

## Home Page

Display:

- Restaurant logo.
- Restaurant name.
- Cover image.
- Description.
- Cuisine.
- Opening hours.
- Address.
- Contact information.
- Ratings if available.
- Current availability.
- Estimated waiting time.
- Book a Table button.
- View Menu button.
- View Gallery button.

## About Us Page

Display restaurant-specific information.

All content must come from the restaurant profile API.

## Menu Page

Display only that restaurant's menu.

Use dynamic categories and items.

## Gallery Page

Display up to five restaurant photos.

## Contact Page

Display:

- Address.
- Phone.
- Email.
- Map.
- Opening hours.
- Social links.

---

# 7. DIGITAL MENU MANAGEMENT

Restaurant owners should have complete control over their digital menu.

Create a dynamic menu management module.

Owners can:

- Create meal types.
- Create categories.
- Create subcategories.
- Add menu items.
- Edit menu items.
- Archive menu items.
- Upload food images.
- Configure prices.
- Configure item variants.
- Configure add-ons.
- Configure taxes.
- Configure availability.
- Configure preparation time.
- Set items as Best Sellers.
- Set items as Today's Special.

## 7.1 Default Meal Types

- Breakfast.
- Brunch.
- Snacks & Quick Bites.
- Lunch.
- Dinner.
- Desserts & Sweets.
- Drinks & Beverages.
- Special Menu.

These should be editable and configurable.

## 7.2 Food Categories

Breakfast:
- Indian Breakfast.
- South Indian Breakfast.
- Continental Breakfast.
- Healthy Breakfast.
- Parathas.
- Eggs & Omelettes.
- Cereals.
- Sandwiches & Toast.

Brunch:
- Brunch Combos.
- Eggs & Omelettes.
- Pancakes & Waffles.
- Sandwiches & Burgers.
- Salads.
- Bakery & Pastries.
- Juices & Smoothies.

Snacks:
- Indian Snacks.
- Street Food.
- Chaat.
- Samosa & Kachori.
- Pakora.
- Fries & Wedges.
- Nachos.
- Spring Rolls.
- Momos.
- Chicken Wings.
- Quick Bites.

Lunch and Dinner:

Starters:
- Veg Starters.
- Non-Veg Starters.
- Tandoori Starters.
- Soups.
- Salads.
- Chinese Starters.

Main Course:
- Veg Main Course.
- Non-Veg Main Course.
- Paneer Dishes.
- Dal & Curries.
- Chinese Main Course.
- Continental Main Course.
- Rice & Biryani.
- Thali & Combos.

Accompaniments:
- Roti.
- Naan.
- Kulcha.
- Paratha.
- Rice.
- Raita.
- Papad.
- Pickles and Chutneys.

Desserts:
- Indian Sweets.
- Cakes.
- Pastries.
- Ice Cream.
- Brownies.
- Puddings.
- Cheesecakes.
- Dessert Combos.

Drinks:

Non-Alcoholic:
- Soft Drinks.
- Fresh Juices.
- Packaged Juices.
- Milkshakes.
- Smoothies.
- Lassi.
- Buttermilk.
- Tea.
- Coffee.
- Hot Chocolate.
- Energy Drinks.
- Mineral Water.

Mocktails:
- Virgin Mojito.
- Fruit Mocktails.
- Iced Tea.
- Lemonades.
- Special Mocktails.

Alcoholic:
- Beer.
- Wine.
- Whisky.
- Vodka.
- Rum.
- Gin.
- Brandy.
- Tequila.
- Cocktails.
- Alcoholic Mojito.
- Other Spirits.

Alcohol categories must remain disabled unless the restaurant is legally authorized to serve alcohol. Enforce applicable local laws and age restrictions.

Special Categories:
- Chef's Special.
- Today's Special.
- Best Sellers.
- Combos.
- Family Packs.
- Kids Menu.
- Healthy Food.
- Vegan Food.
- Jain Food.
- Gluten-Free Food.
- Seasonal Specials.

All default categories should be editable by restaurant owners.

## 7.3 Menu Item Information

Each item should support:

- Name.
- Description.
- Image.
- Price.
- Food classification.
- Spice level.
- Allergens.
- Preparation time.
- Variants.
- Add-ons.
- Special instructions.
- Available days.
- Available time slots.
- Stock availability.
- Bestseller status.

---

# 8. INVENTORY MANAGEMENT

Build a dedicated inventory management module for restaurant owners.

The restaurant owner should be able to manage raw materials and stock used in food preparation.

## 8.1 Inventory Items

Each inventory item should have:

- Item name.
- SKU or internal code.
- Category.
- Unit of measurement.
- Current stock.
- Minimum stock.
- Reorder level.
- Purchase price.
- Supplier.
- Expiry date where applicable.
- Storage location.
- Active status.

Units may include:

- Kilogram.
- Gram.
- Litre.
- Millilitre.
- Pieces.
- Packets.
- Boxes.

## 8.2 Stock Management

Support:

- Opening stock.
- Purchase entries.
- Stock additions.
- Stock deductions.
- Wastage.
- Damaged stock.
- Stock adjustments.
- Stock transfers between branches.
- Stock returns.
- Inventory history.

Maintain a complete stock movement ledger.

Never modify stock silently.

Every stock adjustment must have a reason and audit record.

## 8.3 Supplier Management

Restaurant owners should be able to:

- Add suppliers.
- Edit suppliers.
- Store supplier contact information.
- Record purchases.
- View purchase history.
- Track supplier payments if enabled.

## 8.4 Purchase Management

Implement:

- Purchase orders.
- Purchase invoices.
- Supplier information.
- Purchase date.
- Item quantities.
- Purchase price.
- Tax.
- Total purchase amount.
- Payment status.

## 8.5 Recipe and Ingredient Mapping

Allow restaurant owners to map menu items to ingredients.

Example:

Paneer Butter Masala:
- Paneer: 150 grams.
- Butter: 20 grams.
- Tomato: 100 grams.
- Cream: 30 ml.
- Spices: configured quantities.

When an order is confirmed or enters the restaurant's configured stock-consumption stage, deduct the required ingredients.

Choose one clearly defined deduction event and prevent duplicate deductions.

Support stock reservation or deduction policies so that failed and cancelled orders can release or reverse stock appropriately.

## 8.6 Low Stock Alerts

Notify restaurant owners when stock reaches its reorder level.

Display:

- Low stock items.
- Out-of-stock items.
- Expiring items.
- Purchase recommendations.

## 8.7 Inventory Reports

Provide:

- Current inventory.
- Stock movement.
- Purchase history.
- Consumption.
- Wastage.
- Low stock.
- Expiry reports.
- Inventory valuation.

Inventory must be branch-specific, with controlled stock transfers between branches.

---

# 9. BILLING AND POS MANAGEMENT

Build a complete restaurant billing and POS module.

Restaurant owners should be able to manage customer bills and payments.

Features:

- Generate bills.
- View active table bills.
- Add items to bills where permitted.
- Apply authorized discounts.
- Calculate taxes.
- Add service charges.
- Split bills.
- Merge bills where permitted.
- Process payments.
- Generate receipts.
- Print invoices.
- View payment history.
- Handle refunds.
- Close table sessions.

Payment modes:

- Cash.
- UPI.
- Debit/Credit Card.
- Online Payment Gateway.
- Other configurable methods.

All monetary values must use decimal database types.

Maintain immutable invoice records and proper audit history for corrections, refunds and adjustments.

Support tax configuration based on applicable laws and restaurant settings.

### Important distinction

Maintain separate billing systems for:

1. Restaurant customer bills and POS transactions.
2. WaitLess SaaS subscription invoices and payments.

These must not be mixed.

---

# 10. DIGITAL QUEUE MANAGEMENT

Support walk-in customers.

Customer flow:

1. Customer visits the restaurant.
2. Scans QR code or opens the restaurant storefront.
3. Enters party size and required contact information.
4. Joins the digital queue.
5. Receives a queue token.
6. Views queue position.
7. Views estimated waiting time.
8. Receives a notification when a table is available.
9. Staff assigns a table.
10. Customer is seated.

Staff should be able to:

- Add walk-in customers.
- View queue.
- Update queue position.
- Assign tables.
- Notify customers.
- Cancel queue entries.
- Skip entries.
- Mark no-show.
- View queue history.

Queue updates must be real-time.

---

# 11. TABLE MANAGEMENT

Restaurant owners can:

- Add tables.
- Edit tables.
- Delete or deactivate tables.
- Configure table capacity.
- Assign table sections.
- View table availability.
- Assign customers.
- Transfer customers.
- Release tables.

Table statuses:

- Available.
- Reserved.
- Occupied.
- Cleaning.

Visual representation:

- Green: Available.
- Yellow: Reserved.
- Red: Occupied.
- Blue: Cleaning.

Prevent double assignments using database transactions and appropriate constraints.

---

# 12. ADVANCE RESERVATION MANAGEMENT

Customers can reserve tables in two ways.

## Free Booking

- No booking fee.
- Table reservation is confirmed according to restaurant policy.
- Customer can view the menu.
- Customer cannot place an order before arrival.
- Customer places the order after reaching the restaurant.
- Staff confirms arrival.
- Restaurant accepts the order.
- The 15-minute serving timer starts.

## Paid Booking

- Customer pays a configurable booking fee.
- Payment must be verified by the backend.
- Reservation becomes confirmed.
- Customer can view the menu.
- Customer can place a pre-order before arrival.
- Customer can see the total order amount.
- Restaurant receives the advance order.

### Paid Pre-order Arrival Rule

The 15-minute serving timer must start only after:

1. Customer physically reaches the restaurant.
2. Staff verifies the reservation.
3. Staff clicks Confirm Arrival.

The backend records the server-side timestamp.

For paid advance orders:

sla_started_at = staff_confirmed_at.

Do not start the timer when the customer places the pre-order.

### Reservation Expiry

If the customer does not arrive within the arrival window plus the configured grace period:

- Reservation expires.
- Reserved table becomes available.
- Customer receives a notification.
- Refund or fee forfeiture follows the configured policy.

Never release a checked-in table through an expiry job.

---

# 13. FOOD ORDERING AND KITCHEN MANAGEMENT

Create a digital ordering system.

Customer can:

- Browse menu.
- Select items.
- Select variants.
- Add extras.
- Add instructions.
- Change quantities.
- View cart.
- View taxes.
- View total amount.
- Place order.
- Track order.

Kitchen order statuses:

- Placed.
- Accepted.
- Preparing.
- Ready.
- Served.
- Cancelled.

Kitchen staff can update order status.

Waiter or authorized staff must mark an order as Served.

Ready is not the same as Served.

Support advance orders and walk-in orders.

If user give order to waiter /staff. Then staff will select table number and place order,  and share order ID with customer so that Customer can directly visit to resturant page and instead of book table he can directly enter order ID and see their order order place time remaining time to serve. And Discount details. Customer can place their further order from application also. Once customer finish their food hi can click on finish button. Customer total bill with changes and discount will be shown on final invoice . Customer can pay bill from their directly

---

# 14. 15-MINUTE SERVING PROMISE AND AUTOMATIC DISCOUNT

Default policy:

- Up to 15 minutes: 0% discount.
- More than 15 minutes: 2%.
- Every additional 5 minutes: +2%.
- Maximum discount configurable.

Example:

| Serving time | Discount |
|---|---:|
| Up to 15 min | 0% |
| More than 15 to 20 min | 2% |
| More than 20 to 25 min | 4% |
| More than 25 to 30 min | 6% |
| More than 30 to 35 min | 8% |

Formula:

discount_percentage = min(
    maximum_discount,
    ceil((elapsed_minutes - initial_minutes) / interval_minutes)
    * discount_increment
)

Restaurant owners can configure:

- Serving time.
- Initial discount.
- Additional interval.
- Additional discount.
- Maximum discount.
- Eligible order types.
- Discount calculation base.

Timer start rules:

Walk-in:
When the restaurant accepts the order.

Free advance booking:
After arrival confirmation and order acceptance.

Paid advance booking:
When staff confirms customer arrival.

Use UTC server timestamps.

Save a policy snapshot for each order.

Support automatic real-time discount calculation.

The customer should see:
- Timer.
- Remaining time.
- Serving status.
- Current discount.
- Discount amount.
- Final bill.

Use an order-level SLA initially, where an order is served when all items have been delivered.

---

# 15. RESTAURANT DASHBOARD

Create a complete restaurant admin dashboard.

Main sections:

- Dashboard.
- Restaurant Profile.
- Branding.
- Gallery.
- Branches.
- Employees.
- Tables.
- Queue.
- Reservations.
- Orders.
- Kitchen.
- Menu.
- Categories.
- Inventory.
- Suppliers.
- Purchases.
- Billing.
- Payments.
- Discount Settings.
- Reports.
- Restaurant Settings.

Dashboard statistics:

- Today's revenue.
- Total orders.
- Active orders.
- Active reservations.
- Queue length.
- Available tables.
- Occupied tables.
- Average waiting time.
- Average serving time.
- Delayed orders.
- Total discounts.
- Low inventory alerts.

---

# 16. WAITLESS SUPER ADMIN DASHBOARD

I will control the complete platform.

Super Admin modules:

### Platform Overview
- Total restaurants.
- Active restaurants.
- Pending restaurants.
- Suspended restaurants.
- Total branches.
- Registered customers.
- Total orders.
- Total reservations.
- SaaS revenue.

### Restaurant Management
- Register restaurant.
- Approve restaurant.
- Edit restaurant.
- Activate restaurant.
- Suspend restaurant.
- Deactivate restaurant.
- View restaurant details.
- View usage.

### Subscription Management
- Create plans.
- Edit plans.
- Set plan prices.
- Set usage limits.
- Assign subscriptions.
- Upgrade and downgrade plans.
- Manage renewals.
- Track expired subscriptions.

### Platform Content Management

Allow Super Admin to manage WaitLess public website content:

- About Us.
- Features.
- How It Works.
- Contact details.
- Landing page sections.
- Platform branding.
- Terms and privacy pages.

### Platform Support
- View support requests.
- Manage complaints.
- Track restaurant issues.
- Maintain internal notes.

### Audit and Administration
- Platform audit logs.
- Administrator activity.
- System settings.
- Integration settings.

---

# 17. SAAS SUBSCRIPTION MANAGEMENT

Create configurable subscription plans.

Example:

Starter:
- Limited branches.
- Basic menu.
- Queue management.
- Table management.

Professional:
- Multiple branches.
- Reservations.
- Digital ordering.
- Inventory.
- Billing.
- Analytics.

Enterprise:
- Advanced analytics.
- Higher limits.
- Advanced controls.
- Priority support.
- Custom integrations.

Make features and limits configurable.

Super Admin must be able to create future plans without code changes.

---

# 18. TECHNICAL ARCHITECTURE

Use the following stack.

## Frontend

- Angular 20+.
- Standalone components.
- TypeScript.
- Angular Signals.
- RxJS.
- Angular Router.
- Reactive Forms.
- Angular Material.
- Bootstrap 5 where appropriate.
- SCSS.
- Socket.IO Client.
- Chart.js.

## Backend

- Python 3.12+.
- FastAPI.
- Pydantic v2.
- SQLAlchemy 2.x.
- Alembic.
- PostgreSQL.
- Redis.
- Socket.IO.
- Celery or equivalent background worker.
- JWT authentication.
- OpenAPI/Swagger.

## Infrastructure

- Docker.
- Docker Compose.
- Nginx.
- Cloud hosting.
- Object storage.
- CI/CD.
- Centralized logging.

---

# 19. MULTI-TENANT ARCHITECTURE AND DYNAMIC STOREFRONT

Every restaurant must be a tenant.

Each restaurant can have multiple branches.

Use tenant_id and branch_id for restaurant-owned records.

Never trust tenant information provided by the frontend.

Resolve tenant context using authenticated membership or the requested public restaurant slug.

Public storefront APIs must return only published, public information for the selected tenant.

Private APIs must enforce tenant and branch authorization.

Use composite foreign keys and appropriate PostgreSQL constraints to prevent cross-tenant relationships.

## Dynamic Angular Architecture

Do not create a separate frontend for every restaurant.

Build one reusable Angular storefront.

Suggested route structure:

`/` – WaitLess Landing Page

`/about` – WaitLess About Us

`/restaurants` – Restaurant Discovery

`/r/:slug` – Restaurant Homepage

`/r/:slug/menu` – Restaurant Menu

`/r/:slug/gallery` – Restaurant Gallery

`/r/:slug/reservations` – Restaurant Reservations

`/r/:slug/about` – Restaurant About Us

`/r/:slug/contact` – Restaurant Contact

`/restaurant-admin/**` – Restaurant Admin

`/super-admin/**` – WaitLess Super Admin

`/customer/**` – Customer Account

Use separate layouts for:

- WaitLess public website.
- Restaurant customer storefront.
- Restaurant admin dashboard.
- Super Admin dashboard.

Use shared reusable components wherever possible.

---

# 20. REUSABLE COMPONENT ARCHITECTURE

The application must be modular.

The same component should be reused across restaurants with dynamic input data.

Examples:

- RestaurantHeaderComponent.
- RestaurantLogoComponent.
- RestaurantHeroComponent.
- RestaurantGalleryComponent.
- RestaurantMenuComponent.
- MenuCategoryComponent.
- MenuItemCardComponent.
- RestaurantAvailabilityComponent.
- ReservationFormComponent.
- BookingOptionComponent.
- CartComponent.
- OrderTrackingComponent.
- ServingTimerComponent.
- BillSummaryComponent.
- RestaurantFooterComponent.

For example, RestaurantHeaderComponent should accept restaurant configuration as input.

It should not contain restaurant-specific hardcoded data.

When restaurant context changes, the component should display the new restaurant's information.

Use Angular Signals or an appropriate state service to manage the current restaurant context.

Avoid unnecessary full-page reloads when switching between restaurant storefronts.

Clear or refresh tenant-specific cached state when changing restaurant context.

Prevent stale menus, carts, gallery images and availability data from leaking between tenants.

---

# 21. BACKEND MODULAR ARCHITECTURE

Use a modular FastAPI monolith initially.

Suggested structure:

backend/
  app/
    main.py
    core/
    api/
      v1/
        auth/
        tenants/
        restaurants/
        branches/
        customers/
        staff/
        tables/
        queues/
        reservations/
        menus/
        orders/
        kitchen/
        inventory/
        suppliers/
        purchases/
        billing/
        payments/
        subscriptions/
        notifications/
        analytics/
        super_admin/
    models/
    schemas/
    repositories/
    services/
    middleware/
    websocket/
    tasks/
    utils/
  alembic/
  tests/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example

Keep route handlers, business logic, database models and validation schemas separate.

Do not put all business logic in API endpoints.

---

# 22. DATABASE MODULES

Use PostgreSQL with Alembic migrations.

At minimum, implement these groups of tables.

### Platform and Tenant

- tenants
- branches
- users
- user_branches
- roles
- permissions
- role_permissions
- plans
- plan_features
- subscriptions
- audit_logs

### Restaurant Profile

- restaurant_profiles
- restaurant_branding
- restaurant_gallery
- restaurant_business_hours
- restaurant_social_links

Enforce a maximum of five active gallery images per restaurant.

### Restaurant Operations

- restaurant_tables
- table_sections
- table_sessions
- table_assignments
- queue_sessions
- queue_entries

### Reservations

- reservations
- reservation_tables
- reservation_policies
- reservation_payments

### Menu

- menu_meal_types
- menu_categories
- menu_subcategories
- menu_items
- menu_item_variants
- menu_item_addons
- menu_item_availability
- menu_item_tags

### Inventory

- inventory_categories
- inventory_items
- inventory_stock
- inventory_movements
- suppliers
- purchase_orders
- purchase_order_items
- stock_transfers
- recipes
- recipe_ingredients
- inventory_adjustments

### Orders and Kitchen

- orders
- order_items
- order_item_addons
- order_status_history
- kitchen_order_events
- order_sla
- discount_policies
- order_discounts

### Billing and Payments

- bills
- bill_items
- payments
- refunds
- invoices

### Notifications

- notifications
- notification_templates
- notification_preferences
- notification_delivery_logs

All restaurant-owned records must be tenant-aware.

Use numeric types for money.

Store timestamps in UTC.

Use immutable price and tax snapshots for historical transactions.

Use database transactions and constraints for inventory, table assignment, reservation and payment operations.

---

# 23. API DEVELOPMENT

Create REST APIs under:

`/api/v1/`

Include APIs for:

- Authentication.
- Restaurant registration.
- Restaurant profile.
- Restaurant branding.
- Gallery.
- Restaurant discovery.
- Public restaurant information.
- Availability.
- Queue.
- Tables.
- Reservations.
- Menu.
- Orders.
- Kitchen.
- Inventory.
- Suppliers.
- Purchases.
- Billing.
- Payments.
- Discounts.
- Notifications.
- Analytics.
- Subscriptions.
- Super Admin.

Example public APIs:

GET /api/v1/public/restaurants

GET /api/v1/public/restaurants/{slug}

GET /api/v1/public/restaurants/{slug}/branding

GET /api/v1/public/restaurants/{slug}/gallery

GET /api/v1/public/restaurants/{slug}/menu

GET /api/v1/public/restaurants/{slug}/availability

GET /api/v1/public/restaurants/{slug}/wait-time

Example restaurant admin APIs:

PUT /api/v1/restaurant/profile

PUT /api/v1/restaurant/branding

POST /api/v1/restaurant/gallery

DELETE /api/v1/restaurant/gallery/{id}

POST /api/v1/menu/categories

POST /api/v1/menu/items

GET /api/v1/inventory

POST /api/v1/inventory/purchases

GET /api/v1/billing

Example Super Admin APIs:

GET /api/v1/super-admin/restaurants

POST /api/v1/super-admin/restaurants

PATCH /api/v1/super-admin/restaurants/{id}/status

GET /api/v1/super-admin/subscriptions

POST /api/v1/super-admin/plans

Document every endpoint through Swagger.

---

# 24. REAL-TIME COMMUNICATION

Use Socket.IO for:

- Queue updates.
- Table availability.
- Reservation confirmation.
- Reservation expiry.
- Customer arrival.
- Order updates.
- Kitchen updates.
- SLA countdown changes.
- Discount changes.
- Inventory alerts where appropriate.

Use tenant- and branch-specific rooms.

Authorize every connection and subscription.

Persist business state in PostgreSQL before broadcasting updates.

Use Redis for cross-instance event coordination.

---

# 25. NOTIFICATION SYSTEM

Support:

- In-app notifications.
- SMS.
- WhatsApp.
- Email.
- Push notifications where available.

Customer notifications:

- Reservation confirmed.
- Payment successful.
- Queue token generated.
- Table available.
- Reservation expiring.
- Reservation expired.
- Order placed.
- Order accepted.
- Order ready.
- Order served.
- Discount applied.
- Bill generated.

Restaurant notifications:

- New reservation.
- New pre-order.
- New walk-in.
- Queue update.
- Low inventory.
- Delayed order.
- Payment notification.

---

# 26. SECURITY

Implement:

- JWT authentication.
- Refresh-token rotation.
- Secure password hashing.
- Role-based authorization.
- Tenant isolation.
- Branch authorization.
- Input validation.
- Rate limiting.
- Secure file uploads.
- Payment webhook verification.
- Audit logging.
- CORS configuration.
- HTTPS.
- Secrets management.

Protect against:

- Cross-tenant access.
- Duplicate payments.
- Duplicate orders.
- Table double assignment.
- Reservation expiry race conditions.
- Unauthorized stock adjustments.
- Unauthorized billing changes.
- Unauthorized discounts.

---

# 27. TESTING

Use:

Backend:
- pytest.
- Integration tests.
- API tests.

Frontend:
- Angular unit testing.
- Component testing.
- End-to-end testing with Playwright.

Test these critical scenarios:

1. Super Admin registers and activates a restaurant.
2. Restaurant owner logs in.
3. Owner uploads a logo and five gallery images.
4. Restaurant storefront displays its own branding.
5. Customer switches between two restaurants.
6. Restaurant A data never appears in Restaurant B's storefront.
7. Restaurant owner creates menu categories and items.
8. Customer places a free reservation.
9. Customer cannot pre-order under free booking.
10. Customer pays booking fee and receives pre-order access.
11. Staff confirms arrival and the paid pre-order SLA starts.
12. Customer receives the correct delayed-serving discount.
13. Inventory is deducted correctly.
14. Customer receives a correct bill.
15. Super Admin can manage subscriptions.
16. Unauthorized users cannot access other tenants.
17. Duplicate operations are safely handled.

---

# 28. DEVELOPMENT PHASES

Develop the application incrementally.

### Phase 1 – Foundation
- Angular project.
- FastAPI project.
- PostgreSQL.
- Redis.
- Docker.
- Database migrations.
- Common architecture.

### Phase 2 – Authentication and SaaS
- Super Admin.
- Restaurant Admin.
- Customers.
- Roles.
- Permissions.
- Tenant creation.
- Branches.

### Phase 3 – Restaurant Profile and Branding
- Restaurant profile.
- Logo upload.
- Five-photo gallery.
- Theme settings.
- Restaurant slug.
- Public storefront API.

### Phase 4 – Dynamic Restaurant Storefront
- WaitLess landing page.
- Restaurant discovery.
- Restaurant-specific layouts.
- Dynamic restaurant header.
- Restaurant menu.
- Gallery.
- About Us.
- WaitLess return navigation.

### Phase 5 – Restaurant Administration
- Restaurant dashboard.
- Branch management.
- Employee management.
- Table management.

### Phase 6 – Queue and Reservations
- Digital queue.
- Free bookings.
- Paid bookings.
- Booking payments.
- Arrival confirmation.
- Reservation expiry.

### Phase 7 – Menu and Ordering
- Meal types.
- Categories.
- Menu items.
- Variants.
- Add-ons.
- Cart.
- Pre-orders.
- Kitchen dashboard.

### Phase 8 – SLA and Discounts
- 15-minute timer.
- Discount policy.
- Automatic discount.
- Live updates.
- Final bill.

### Phase 9 – Inventory
- Stock management.
- Suppliers.
- Purchases.
- Recipes.
- Stock deduction.
- Low stock alerts.

### Phase 10 – Billing and Payments
- Restaurant POS.
- Customer bills.
- Payments.
- Receipts.
- Refunds.

### Phase 11 – Analytics and SaaS Admin
- Reports.
- Subscription plans.
- SaaS billing.
- Platform analytics.

### Phase 12 – Production
- Security testing.
- Performance testing.
- End-to-end testing.
- Deployment.
- Monitoring.
- Backups.

---

# 29. DEVELOPMENT RULES

Follow these rules strictly.

1. Build a modular application.
2. Use reusable Angular components.
3. Use a shared dynamic restaurant storefront.
4. Never hardcode restaurant information.
5. Never create a separate Angular deployment for each restaurant.
6. Make branding configurable.
7. Use tenant-aware backend services.
8. Keep business logic in FastAPI services.
9. Use PostgreSQL as the source of truth.
10. Use Redis for caching and real-time coordination.
11. Make the application responsive.
12. Use proper loading, empty and error states.
13. Implement real backend functionality, not static mock screens.
14. Use environment variables for configurations.
15. Use Alembic for migrations.
16. Write automated tests.
17. Maintain API documentation.
18. Avoid duplicate code.
19. Do not mix restaurant billing with WaitLess subscription billing.
20. Keep all business policies configurable where appropriate.

Before implementation, produce:

- System architecture diagram.
- Database ER diagram.
- Module dependency diagram.
- User role and permission matrix.
- Customer journey flow.
- Restaurant admin journey flow.
- Super Admin journey flow.
- API specification.
- Development plan.

Then implement the project phase by phase.

After completing every phase:

- List implemented features.
- List created and modified files.
- Explain database changes.
- List APIs.
- Run tests.
- Document known issues.
- Provide instructions to run the application.

Do not claim that a feature is complete until its frontend, backend, database and relevant tests are implemented.

---

# 30. FINAL EXPECTED DELIVERABLES

Deliver:

1. Complete Angular frontend.
2. Complete FastAPI backend.
3. PostgreSQL schema.
4. Alembic migrations.
5. ER diagram.
6. API documentation.
7. WaitLess landing page.
8. Dynamic restaurant storefront.
9. Super Admin dashboard.
10. Restaurant Admin dashboard.
11. Customer application.
12. Gallery and branding management.
13. Menu management.
14. Inventory management.
15. Billing and POS.
16. Queue and reservation management.
17. Digital ordering.
18. Kitchen display system.
19. SLA and discount engine.
20. Payment integrations.
21. Notification system.
22. SaaS subscription management.
23. Analytics and reporting.
24. Automated tests.
25. Docker configuration.
26. Deployment documentation.

# FINAL PRODUCT EXPECTATION

WaitLess should work like a restaurant technology platform where every registered restaurant gets its own digital identity.

For example:

When a customer visits:

`www.waitless.com`

They see the WaitLess platform, its About Us page, features, services and restaurant discovery.

When the customer selects:

`www.waitless.com/r/urban-bites`

The application dynamically becomes the Urban Bites customer experience.

It displays:
- Urban Bites logo.
- Urban Bites restaurant name.
- Urban Bites gallery.
- Urban Bites About Us.
- Urban Bites menu.
- Urban Bites table availability.
- Urban Bites reservations.
- Urban Bites ordering.

The WaitLess option remains visible in the header. Clicking it returns the customer to the main WaitLess website.

Restaurant owners manage their own branding, menus, inventory, employees, orders, tables and billing through their independent admin dashboards.

I, as the WaitLess Super Admin, control the entire SaaS platform, including restaurant registration, activation, subscriptions, plans and platform-wide settings.

**The goal is to build a scalable, secure, modular, reusable and production-ready restaurant SaaS platform, not just a restaurant website or food ordering application.**
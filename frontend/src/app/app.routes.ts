import { Routes } from '@angular/router';

import type { AdminNavItem } from './layouts/admin-layout/admin-layout.component';

/** Route map follows docs/01 + PRD §19. Each area is lazy-loaded with its own layout. */

const placeholder = () =>
  import('./shared/ui/placeholder-page/placeholder-page.component').then((m) => m.PlaceholderPageComponent);

const page = (path: string, title: string, phase: number) => ({
  path,
  loadComponent: placeholder,
  title: `${title} · WaitLess`,
  data: { title, phase },
});

const RESTAURANT_ADMIN_NAV: AdminNavItem[] = [
  { label: 'Dashboard', icon: 'dashboard', path: '.' },
  { label: 'Restaurant Profile', icon: 'storefront', path: 'profile' },
  { label: 'Branding', icon: 'palette', path: 'branding' },
  { label: 'Gallery', icon: 'photo_library', path: 'gallery' },
  { label: 'Branches', icon: 'account_tree', path: 'branches' },
  { label: 'Employees', icon: 'badge', path: 'employees' },
  { label: 'Tables', icon: 'table_restaurant', path: 'tables' },
  { label: 'Queue', icon: 'groups', path: 'queue' },
  { label: 'Reservations', icon: 'event_seat', path: 'reservations' },
  { label: 'Orders', icon: 'receipt_long', path: 'orders' },
  { label: 'Kitchen', icon: 'soup_kitchen', path: 'kitchen' },
  { label: 'Menu', icon: 'restaurant_menu', path: 'menu' },
  { label: 'Inventory', icon: 'inventory_2', path: 'inventory' },
  { label: 'Suppliers', icon: 'local_shipping', path: 'suppliers' },
  { label: 'Purchases', icon: 'shopping_cart', path: 'purchases' },
  { label: 'Billing', icon: 'point_of_sale', path: 'billing' },
  { label: 'Payments', icon: 'payments', path: 'payments' },
  { label: 'Discount Settings', icon: 'timer', path: 'discounts' },
  { label: 'Reports', icon: 'monitoring', path: 'reports' },
  { label: 'Settings', icon: 'settings', path: 'settings' },
];

const SUPER_ADMIN_NAV: AdminNavItem[] = [
  { label: 'Overview', icon: 'insights', path: '.' },
  { label: 'Restaurants', icon: 'storefront', path: 'restaurants' },
  { label: 'Plans', icon: 'workspace_premium', path: 'plans' },
  { label: 'Subscriptions', icon: 'autorenew', path: 'subscriptions' },
  { label: 'Content', icon: 'article', path: 'content' },
  { label: 'Support', icon: 'support_agent', path: 'support' },
  { label: 'Audit Logs', icon: 'policy', path: 'audit' },
  { label: 'Settings', icon: 'settings', path: 'settings' },
];

/** Builds child routes for an admin area from its nav list, with the phase each one ships in. */
const adminChildren = (nav: AdminNavItem[], phases: Record<string, number>) =>
  nav.map((n) => page(n.path === '.' ? '' : n.path, n.label, phases[n.path] ?? 0));

export const routes: Routes = [
  // WaitLess public website
  {
    path: '',
    loadComponent: () =>
      import('./layouts/platform-layout/platform-layout.component').then((m) => m.PlatformLayoutComponent),
    children: [
      {
        path: '',
        title: 'WaitLess · Skip the Wait. Dine Delightfully!',
        loadComponent: () => import('./features/platform/home/home.page').then((m) => m.HomePage),
      },
      {
        path: 'status',
        title: 'System status · WaitLess',
        loadComponent: () => import('./features/platform/status/status.page').then((m) => m.StatusPage),
      },
      page('about', 'About WaitLess', 4),
      page('restaurants', 'Find Restaurants', 4),
      page('login', 'Login / Register', 2),
      page('register-restaurant', 'Register your restaurant', 2),
      {
        path: 'customer',
        children: [page('', 'My Account', 6), page('bookings', 'My Bookings', 6), page('orders', 'My Orders', 7)],
      },
    ],
  },

  // Restaurant storefront (one reusable storefront for every tenant)
  {
    path: 'r/:slug',
    loadComponent: () =>
      import('./layouts/storefront-layout/storefront-layout.component').then((m) => m.StorefrontLayoutComponent),
    children: [
      page('', 'Restaurant Home', 4),
      page('menu', 'Menu', 4),
      page('gallery', 'Gallery', 4),
      page('about', 'About Us', 4),
      page('reservations', 'Reservations', 6),
      page('contact', 'Contact', 4),
      page('cart', 'Cart', 7),
      page('session', 'My Table', 7),
    ],
  },

  // Restaurant admin dashboard
  {
    path: 'restaurant-admin',
    loadComponent: () => import('./layouts/admin-layout/admin-layout.component').then((m) => m.AdminLayoutComponent),
    data: { area: 'Restaurant Admin', nav: RESTAURANT_ADMIN_NAV },
    children: adminChildren(RESTAURANT_ADMIN_NAV, {
      '.': 5, profile: 3, branding: 3, gallery: 3, branches: 5, employees: 5, tables: 5, queue: 6,
      reservations: 6, orders: 7, kitchen: 7, menu: 4, inventory: 9, suppliers: 9, purchases: 9,
      billing: 10, payments: 10, discounts: 8, reports: 11, settings: 5,
    }),
  },

  // WaitLess Super Admin dashboard
  {
    path: 'super-admin',
    loadComponent: () => import('./layouts/admin-layout/admin-layout.component').then((m) => m.AdminLayoutComponent),
    data: { area: 'Super Admin', nav: SUPER_ADMIN_NAV },
    children: adminChildren(SUPER_ADMIN_NAV, {
      '.': 11, restaurants: 2, plans: 11, subscriptions: 11, content: 11, support: 11, audit: 11, settings: 11,
    }),
  },

  {
    path: '**',
    title: 'Not found · WaitLess',
    loadComponent: () => import('./features/not-found/not-found.page').then((m) => m.NotFoundPage),
  },
];

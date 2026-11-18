import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

/**
 * Which restaurant-admin pages a role can open. A page opens when the role has ANY of its
 * permissions — the same permissions the backend checks on that page's APIs, so the owner
 * controls page access by editing the role (Employees → Roles). Pages without an entry
 * (Dashboard, Settings) are open to every staff member.
 */
export const PAGE_ACCESS: Record<string, { label: string; perms: string[] }> = {
  profile: { label: 'Restaurant Profile', perms: ['restaurant.profile.view', 'restaurant.profile.manage'] },
  branding: { label: 'Branding', perms: ['restaurant.branding.manage'] },
  gallery: { label: 'Gallery', perms: ['restaurant.gallery.manage'] },
  branches: { label: 'Branches', perms: ['branches.view', 'branches.manage'] },
  employees: { label: 'Employees', perms: ['staff.manage'] },
  tables: { label: 'Tables', perms: ['tables.operate', 'tables.configure'] },
  queue: { label: 'Queue', perms: ['queue.manage'] },
  reservations: { label: 'Reservations', perms: ['reservations.view', 'reservations.manage'] },
  orders: { label: 'Orders', perms: ['orders.view', 'orders.create'] },
  kitchen: { label: 'Kitchen', perms: ['kitchen.operate'] },
  menu: { label: 'Menu', perms: ['menu.manage', 'menu.basic', 'menu.availability.toggle'] },
  inventory: { label: 'Inventory', perms: ['inventory.view', 'inventory.adjust'] },
  suppliers: { label: 'Suppliers', perms: ['suppliers.manage', 'purchases.manage'] },
  purchases: { label: 'Purchases', perms: ['purchases.manage'] },
  billing: { label: 'Billing', perms: ['billing.operate', 'payments.collect'] },
  payments: { label: 'Payments', perms: ['payments.collect', 'payments.refund'] },
  discounts: { label: 'Discount Settings', perms: ['discounts.policy.manage'] },
  reports: { label: 'Reports', perms: ['reports.view', 'reports.sales.view'] },
  reviews: { label: 'Reviews', perms: ['restaurant.profile.view', 'restaurant.profile.manage'] },
};

/** First path segment under /restaurant-admin, e.g. "tables/qr" → "tables". */
export function pageKey(path: string): string {
  return path.split('/')[0];
}

export function canOpenPage(path: string, has: (perm: string) => boolean): boolean {
  const rule = PAGE_ACCESS[pageKey(path)];
  return !rule || rule.perms.some(has);
}

/** Route guard: a staff member without any of the page's permissions goes to the dashboard. */
export const pageAccessGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const path = route.routeConfig?.path ?? '';
  return canOpenPage(path, (p) => auth.hasPermission(p)) || inject(Router).createUrlTree(['/restaurant-admin']);
};

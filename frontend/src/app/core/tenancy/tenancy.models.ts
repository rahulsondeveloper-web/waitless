import { SubscriptionInfo, TenantStatus } from '../auth/auth.models';

export type { TenantStatus };

/** Mirrors backend app/schemas/tenancy.py. */

export const RESTAURANT_TYPES = [
  'Fine Dining',
  'Casual Dining',
  'Cafe',
  'Quick Service',
  'Bar & Restaurant',
  'Bakery & Desserts',
  'Cloud Kitchen',
  'Food Court',
  'Other',
] as const;

export const CUISINES = [
  'North Indian',
  'South Indian',
  'Chinese',
  'Italian',
  'Continental',
  'Mughlai',
  'Street Food',
  'Cafe & Bakery',
  'Desserts',
  'Beverages',
  'Pan-Asian',
  'Mexican',
  'Seafood',
  'Healthy',
] as const;

export interface RestaurantRegistration {
  restaurant_name: string;
  owner_name: string;
  email: string;
  mobile: string;
  password: string;
  address: string;
  city: string;
  state: string;
  country: string;
  cuisines: string[];
  restaurant_type: string;
  number_of_branches: number;
  preferred_slug?: string | null;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  status_reason: string | null;
  is_published: boolean;
  restaurant_type: string;
  cuisines: string[];
  declared_branch_count: number;
  created_at: string;
  approved_at: string | null;
}

export interface Branch {
  id: string;
  name: string;
  address_line: string;
  city: string;
  state: string;
  country: string;
  postal_code: string | null;
  timezone: string;
  phone: string | null;
  is_primary: boolean;
  is_active: boolean;
}

export interface RestaurantMe {
  tenant: Tenant;
  subscription: SubscriptionInfo | null;
  branches: Branch[];
}

export interface SlugAvailability {
  slug: string;
  available: boolean;
  suggestion: string | null;
}

export interface RestaurantAdminRow extends Tenant {
  owner: { id: string; full_name: string; email: string | null; phone: string | null } | null;
  city: string | null;
  subscription: SubscriptionInfo | null;
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export type StatusAction = 'approve' | 'reject' | 'activate' | 'suspend' | 'deactivate';

/** Mirrors TRANSITIONS in backend app/services/super_admin.py. */
export const STATUS_ACTIONS: Record<TenantStatus, StatusAction[]> = {
  pending: ['approve', 'reject', 'deactivate'],
  active: ['suspend', 'deactivate'],
  suspended: ['activate', 'deactivate'],
  deactivated: ['activate'],
  rejected: ['activate'],
};

export const REASON_REQUIRED: ReadonlySet<StatusAction> = new Set(['reject', 'suspend', 'deactivate']);

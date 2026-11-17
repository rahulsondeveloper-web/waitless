/** Mirrors backend public schemas (profile.StorefrontOut, menu.PublicMenu, discovery.*). */
import { Gallery, HoursDay, SocialLink } from '../restaurant/restaurant.models';
import { Branding } from '../theme/theme.tokens';

export type { Gallery };

export interface PublicBranch {
  id: string;
  name: string;
  address_line: string;
  city: string;
  state: string;
  country: string;
  postal_code: string | null;
  lat: string | null;
  lng: string | null;
  phone: string | null;
  timezone: string;
  is_primary: boolean;
  hours: HoursDay[];
  open_now: boolean;
  today_hours: string | null;
}

export interface Storefront {
  id: string;
  name: string;
  slug: string;
  restaurant_type: string;
  cuisines: string[];
  currency: string;
  is_published: boolean;
  short_description: string;
  description: string;
  about_us: string;
  contact_phone: string | null;
  contact_email: string | null;
  website: string | null;
  cover_url: string | null;
  branding: Branding;
  branches: PublicBranch[];
  social_links: SocialLink[];
  gallery_count: number;
}

export type FoodClass = 'veg' | 'non_veg' | 'egg';

export interface PublicItem {
  id: string;
  name: string;
  description: string;
  image_url: string | null;
  price: string;
  food_class: FoodClass;
  spice_level: number;
  allergens: string[];
  prep_minutes: number;
  is_bestseller: boolean;
  is_todays_special: boolean;
  is_available: boolean;
  subcategory: string | null;
}

export interface PublicCategory {
  id: string;
  name: string;
  description: string;
  meal_type_ids: string[];
  items: PublicItem[];
}

export interface PublicMenu {
  currency: string;
  meal_types: { id: string; name: string }[];
  categories: PublicCategory[];
}

export interface DiscoveryCard {
  id: string;
  name: string;
  slug: string;
  short_description: string;
  restaurant_type: string;
  cuisines: string[];
  city: string | null;
  address: string | null;
  lat: string | null;
  lng: string | null;
  logo_url: string | null;
  cover_url: string | null;
  primary_color: string | null;
  open_now: boolean;
  today_hours: string | null;
  distance_km: number | null;
  wait_minutes: number | null;
}

export interface DiscoveryPage {
  items: DiscoveryCard[];
  page: number;
  page_size: number;
  total: number;
}

export interface DiscoveryFilters {
  cities: string[];
  cuisines: string[];
  restaurant_types: string[];
}

export interface DiscoveryQuery {
  q?: string | null;
  city?: string | null;
  cuisine?: string | null;
  type?: string | null;
  open_now?: boolean | null;
  lat?: number | null;
  lng?: number | null;
  radius_km?: number | null;
  page?: number;
  page_size?: number;
}

export interface ContactRequest {
  name: string;
  email: string;
  phone?: string | null;
  topic: 'general' | 'restaurant_signup' | 'customer' | 'partnership' | 'other';
  message: string;
  website?: string; // honeypot
}

/** Indian-style price: ₹520, ₹1,815.50 */
export function formatPrice(value: string | number, currency = 'INR'): string {
  const n = typeof value === 'string' ? Number(value) : value;
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export const SOCIAL_LABELS: Partial<Record<string, string>> = {
  instagram: 'Instagram',
  facebook: 'Facebook',
  x: 'X',
  youtube: 'YouTube',
  google: 'Google',
  zomato: 'Zomato',
  swiggy: 'Swiggy',
  tripadvisor: 'Tripadvisor',
  other: 'Website',
};

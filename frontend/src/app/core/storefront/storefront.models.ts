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
  // Phase 7
  tax_pct: string;
  tags: string[];
  variants: MenuVariant[];
  addon_groups: MenuAddonGroup[];
  availability: MenuWindow[]; // empty = whenever the restaurant is open
  branch_overrides: MenuBranchOverride[];
}

export interface MenuVariant {
  id: string;
  name: string;
  price: string;
}

export interface MenuAddon {
  id: string;
  name: string;
  price: string;
}

export interface MenuAddonGroup {
  id: string;
  name: string;
  min_select: number;
  max_select: number;
  addons: MenuAddon[];
}

export interface MenuWindow {
  weekday: number; // 0 = Monday
  from_time: string; // "12:00:00"
  to_time: string;
}

export interface MenuBranchOverride {
  branch_id: string;
  is_available: boolean;
  price_override: string | null;
}

export interface PublicCategory {
  id: string;
  name: string;
  description: string;
  meal_type_ids: string[];
  items: PublicItem[];
  image_url?: string | null;
  /** Dishes matching the filters; more than items.length while the rest load in batches. */
  item_count?: number | null;
}

/** The next batch of a category's dishes ("load more on scroll"). */
export interface PublicItemsPage {
  category_id: string;
  offset: number;
  total: number;
  items: PublicItem[];
}

/** Server-side menu filters + batch size. */
export interface MenuQuery {
  limit?: number;
  veg?: boolean;
  q?: string;
}

export interface PublicMenu {
  currency: string;
  meal_types: { id: string; name: string }[];
  categories: PublicCategory[];
  ordering_enabled: boolean;
  /** Legend marks used anywhere on the menu: bestseller, special, classic, jain, custom. */
  marks?: string[];
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

/**
 * The category card photo: the owner's own, or the template's default for that kind of category
 * (Starters, Main course, Soups, Salads, Desserts, Beverages — the Remelle template's menu section;
 * Pizzas and the bar have their own photos too).
 */
export function categoryImage(name: string, imageUrl: string | null | undefined): string {
  if (imageUrl) return imageUrl;
  const n = name.toLowerCase();
  const pick = (k: string) => `menu-categories/${k}.jpg`;
  if (/(non[- ]?alcoholic|mocktail|drink|beverage|juice|coffee|tea|shake|lassi|smoothie|soda|water)/.test(n)) return pick('beverages');
  if (/(alcohol|cocktail|\bbar\b|wine|beer|whisk|vodka|\brum\b|\bgin\b|spirit|liquor)/.test(n)) return pick('bar');
  if (/(pizza)/.test(n)) return pick('pizza');
  if (/(dessert|sweet|cake|ice ?cream|bakery|pastr|mithai|kulfi)/.test(n)) return pick('desserts');
  if (/(soup|shorba)/.test(n)) return pick('soups');
  if (/(salad|green|bowl)/.test(n)) return pick('salads');
  if (/(starter|appeti|snack|small plate|chaat|tikka|tandoor|breakfast|toast)/.test(n)) return pick('starters');
  return pick('main');
}

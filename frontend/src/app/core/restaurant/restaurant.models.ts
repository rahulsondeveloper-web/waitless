/** Mirrors backend app/schemas/profile.py. */
import { Branding, BrandingColors } from '../theme/theme.tokens';

export type { Branding, BrandingColors };

export interface Profile {
  tenant_id: string;
  name: string;
  slug: string;
  status: string;
  is_published: boolean;
  restaurant_type: string;
  cuisines: string[];
  short_description: string;
  description: string;
  about_us: string;
  contact_phone: string | null;
  contact_email: string | null;
  website: string | null;
  cover_url: string | null;
}

export type ProfileUpdate = Pick<
  Profile,
  'name' | 'restaurant_type' | 'cuisines' | 'short_description' | 'description' | 'about_us'
> & { contact_phone: string | null; contact_email: string | null; website: string | null };

export interface BrandingUpdate {
  tokens: BrandingColors;
  button_style: Branding['button_style'];
  mode: Branding['mode'];
}

export interface GalleryItem {
  id: string;
  url: string;
  width: number;
  height: number;
  position: number;
  caption: string;
}

export interface Gallery {
  items: GalleryItem[];
  max_photos: number;
}

export interface HoursDay {
  weekday: number; // 0 = Monday
  is_closed: boolean;
  opens_at: string | null; // "HH:MM" or "HH:MM:SS"
  closes_at: string | null;
}

export interface Hours {
  branch_id: string;
  days: HoursDay[];
}

export const SOCIAL_PLATFORMS = [
  'instagram',
  'facebook',
  'x',
  'youtube',
  'google',
  'zomato',
  'swiggy',
  'tripadvisor',
  'other',
] as const;
export type SocialPlatform = (typeof SOCIAL_PLATFORMS)[number];

export interface SocialLink {
  platform: SocialPlatform;
  url: string;
}

export interface BranchLocation {
  name: string;
  address_line: string;
  city: string;
  state: string;
  country: string;
  postal_code: string | null;
  lat: string | null;
  lng: string | null;
  phone: string | null;
}

export interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
  required: boolean;
  hint: string;
}

export interface PublishChecklist {
  items: ChecklistItem[];
  can_publish: boolean;
  is_published: boolean;
}

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const;

/** Client-side pre-check mirroring the server limits (the server re-validates everything). */
export const IMAGE_RULES = {
  maxBytes: 5 * 1024 * 1024,
  types: ['image/jpeg', 'image/png', 'image/webp'],
  accept: 'image/jpeg,image/png,image/webp',
} as const;

/** Test data shared by unit tests. */
import { Storefront } from '../core/storefront/storefront.models';

export function storefront(slug: string, name: string, primary: string | null): Storefront {
  return {
    id: slug,
    name,
    slug,
    restaurant_type: 'Cafe',
    cuisines: ['Italian'],
    currency: 'INR',
    is_published: true,
    short_description: '',
    description: '',
    about_us: '',
    contact_phone: null,
    contact_email: null,
    website: null,
    cover_url: null,
    branding: {
      logo_url: null,
      tokens: primary ? { primary } : {},
      button_style: 'pill',
      mode: 'light',
      version: 1,
      is_default: !primary,
    },
    branches: [],
    social_links: [],
    gallery_count: 0,
  };
}

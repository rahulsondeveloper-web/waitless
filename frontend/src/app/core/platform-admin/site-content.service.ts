import { Injectable, inject, signal } from '@angular/core';

import { ApiService } from '../http/api.service';

/** The public WaitLess website's editable content (Super Admin → Content). Loaded once per visit. */

export interface IconText {
  icon: string;
  title: string;
  text: string;
}

export interface SiteContent {
  home: { eyebrow: string; title: string; title_script: string; lead: string };
  how_it_works: { title: string; steps: IconText[] };
  features: { title: string; items: IconText[] };
  for_restaurants: { title: string; benefits: string[]; cta: string };
  about: { title: string; title_script: string; lead: string; vision: string; mission: string };
  contact: { email: string; phone: string; address: string; hours: string };
  branding: { tagline: string; announcement: string };
  terms: { title: string; updated: string; body: string };
  privacy: { title: string; updated: string; body: string };
  platform: { support_email: string; support_phone: string; maintenance_banner: string; allow_registration: boolean };
}

@Injectable({ providedIn: 'root' })
export class SiteContentService {
  private readonly api = inject(ApiService);
  private requested = false;
  /** null until loaded (pages show their built-in text meanwhile). */
  readonly content = signal<SiteContent | null>(null);

  load(): void {
    if (this.requested) return;
    this.requested = true;
    this.api.get<SiteContent>('public/content').subscribe({
      next: (c) => this.content.set(c),
      error: () => (this.requested = false),
    });
  }
}

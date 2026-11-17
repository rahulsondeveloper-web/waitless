import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/** Restaurant About Us (PRD §6) — all content from the restaurant profile API. */
@Component({
  selector: 'wl-storefront-about',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (ctx.restaurant(); as r) {
      <section class="wl-container page">
        <p class="eyebrow">About us</p>
        <h1 class="title">{{ r.name }}</h1>
        <p class="meta">{{ r.restaurant_type }} · {{ r.cuisines.join(' · ') }}</p>
        @if (r.about_us) {
          <div class="story">{{ r.about_us }}</div>
        }
        @if (r.description && r.description !== r.about_us) {
          <div class="story muted">{{ r.description }}</div>
        }
        @if (!r.about_us && !r.description) {
          <p class="muted">{{ r.short_description || 'Our story is coming soon.' }}</p>
        }
        <div class="cta">
          <a routerLink="../menu" class="wl-btn wl-btn--primary">See the menu</a>
          <a routerLink="../contact" class="wl-btn wl-btn--ghost">Visit us</a>
        </div>
      </section>
    }
  `,
  styles: `
    .page {
      padding-block: 3rem;
      max-width: 820px;
    }
    .eyebrow {
      font-size: 0.78rem;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--wl-primary);
    }
    .title {
      font: 600 clamp(2.2rem, 5vw, 3.4rem) / 1.05 var(--wl-font-serif);
    }
    .meta {
      color: var(--wl-muted);
      margin-top: 0.3rem;
    }
    .story {
      margin-top: 1.4rem;
      font-size: 1.05rem;
      line-height: 1.75;
      white-space: pre-line;
    }
    .muted {
      color: var(--wl-text-soft);
    }
    .cta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.7rem;
      margin-top: 2rem;
    }
  `,
})
export class StorefrontAboutPage {
  protected readonly ctx = inject(TenantContextService);
}

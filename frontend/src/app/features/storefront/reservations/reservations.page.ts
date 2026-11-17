import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/** Placeholder in the restaurant's own branding until reservations ship (Phase 6). */
@Component({
  selector: 'wl-storefront-reservations',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-container page">
      <span class="material-symbols-outlined icon" aria-hidden="true">event_seat</span>
      <h1>Table booking is coming soon</h1>
      <p>
        Soon you'll be able to reserve a table at {{ ctx.restaurant()?.name }} — free, or with a small fee that lets you
        pre-order so your food is ready when you arrive.
      </p>
      @if (ctx.restaurant()?.contact_phone; as phone) {
        <p>Until then, call us: <a [href]="'tel:' + phone">{{ phone }}</a></p>
      }
      <a routerLink="../menu" class="wl-btn wl-btn--primary">Browse the menu</a>
    </section>
  `,
  styles: `
    .page {
      display: grid;
      justify-items: center;
      gap: 0.8rem;
      padding-block: 4rem;
      text-align: center;
      max-width: 640px;
    }
    .icon {
      font-size: 3rem;
      color: var(--wl-primary);
    }
    h1 {
      font: 600 clamp(1.8rem, 4vw, 2.6rem) var(--wl-font-serif);
    }
    p {
      color: var(--wl-text-soft);
    }
    a:not(.wl-btn) {
      color: var(--wl-primary);
      font-weight: 600;
    }
  `,
})
export class StorefrontReservationsPage {
  protected readonly ctx = inject(TenantContextService);
}

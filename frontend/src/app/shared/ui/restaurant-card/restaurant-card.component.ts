import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { DiscoveryCard } from '../../../core/storefront/storefront.models';

/** Discovery result card. Uses the restaurant's own primary colour as an accent. */
@Component({
  selector: 'wl-restaurant-card',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let r = restaurant();
    <a class="card" [routerLink]="['/r', r.slug]" [style.--accent]="r.primary_color || null"
       [attr.aria-label]="r.name + ', ' + (r.open_now ? 'open now' : 'closed now')">
      <div class="cover" [style.background-image]="r.cover_url ? 'url(' + r.cover_url + ')' : null">
        <span class="status" [class.status--open]="r.open_now">{{ r.open_now ? 'Open now' : 'Closed' }}</span>
        @if (r.distance_km !== null) { <span class="dist">{{ r.distance_km }} km</span> }
      </div>
      <div class="body">
        <div class="title">
          @if (r.logo_url) {
            <img [src]="r.logo_url" alt="" width="36" height="36" />
          } @else {
            <span class="initial" aria-hidden="true">{{ r.name.charAt(0) }}</span>
          }
          <div>
            <h3>{{ r.name }}</h3>
            <small>{{ r.city }} · {{ r.restaurant_type }}</small>
          </div>
        </div>
        @if (r.short_description) { <p>{{ r.short_description }}</p> }
        <div class="chips">
          @for (c of r.cuisines.slice(0, 3); track c) { <span>{{ c }}</span> }
        </div>
        @if (r.today_hours) { <small class="hours">Today {{ r.today_hours }}</small> }
      </div>
    </a>
  `,
  styles: `
    :host {
      display: block;
      --accent: var(--wl-primary);
    }
    .card {
      display: flex;
      flex-direction: column;
      height: 100%;
      background: var(--wl-surface);
      border: 1px solid var(--wl-line);
      border-radius: var(--wl-radius);
      overflow: hidden;
      box-shadow: var(--wl-shadow-sm);
      transition: transform 0.2s, box-shadow 0.2s;
      &:hover,
      &:focus-visible {
        transform: translateY(-3px);
        box-shadow: var(--wl-shadow);
      }
    }
    .cover {
      position: relative;
      aspect-ratio: 16 / 9;
      background: color-mix(in srgb, var(--accent) 25%, var(--wl-surface-alt)) center / cover no-repeat;
      border-bottom: 4px solid var(--accent);
    }
    .status,
    .dist {
      position: absolute;
      top: 10px;
      padding: 0.1rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      background: rgba(0, 0, 0, 0.6);
      color: #fff;
    }
    .status {
      left: 10px;
    }
    .status--open {
      background: #2f6b2b;
    }
    .dist {
      right: 10px;
    }
    .body {
      display: grid;
      gap: 0.5rem;
      padding: 0.9rem 1rem 1rem;
    }
    .title {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      img {
        width: 36px;
        height: 36px;
        object-fit: contain;
        border-radius: 8px;
      }
      h3 {
        font: 600 1.2rem/1.1 var(--wl-font-serif);
      }
      small {
        color: var(--wl-muted);
      }
    }
    .initial {
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
    }
    p {
      font-size: 0.88rem;
      color: var(--wl-text-soft);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
      span {
        padding: 0 0.55rem;
        border-radius: 999px;
        background: var(--wl-surface-alt);
        font-size: 0.75rem;
      }
    }
    .hours {
      color: var(--wl-muted);
      font-size: 0.78rem;
    }
  `,
})
export class RestaurantCardComponent {
  readonly restaurant = input.required<DiscoveryCard>();
}

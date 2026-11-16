import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { ThemeTokens, tokensToCssVars } from '../../../core/theme/theme.tokens';

/**
 * Miniature storefront rendered with a theme scoped to this element (CSS variables on the host),
 * so owners see their branding live without affecting the admin UI (PRD §5.4 "live preview").
 */
@Component({
  selector: 'wl-storefront-preview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[style]': 'vars()', role: 'img', '[attr.aria-label]': '"Preview of " + name() + " storefront"' },
  template: `
    <div class="pv">
      <header class="pv-head">
        @if (logoUrl()) {
          <img [src]="logoUrl()" alt="" class="pv-logo" />
        } @else {
          <span class="pv-initial">{{ name().charAt(0) || 'R' }}</span>
        }
        <b class="pv-name">{{ name() }}</b>
        <nav><span>Menu</span><span>Gallery</span><span class="pv-wl">WaitLess</span></nav>
      </header>
      <section class="pv-hero" [style.background-image]="coverUrl() ? 'url(' + coverUrl() + ')' : null">
        <div class="pv-hero__text">
          <p class="pv-eyebrow">Welcome to</p>
          <h3>{{ name() }}</h3>
          <p class="pv-tag">{{ tagline() || 'Good food brings people together' }}</p>
          <div class="pv-ctas">
            <span class="pv-btn pv-btn--primary">Book a table</span>
            <span class="pv-btn pv-btn--ghost">View menu</span>
          </div>
        </div>
      </section>
      <section class="pv-menu">
        <div class="pv-item">
          <div>
            <b>Grilled Salmon <span class="pv-badge">Chef's special</span></b>
            <small>Lemon butter sauce, seasonal vegetables</small>
          </div>
          <span class="pv-price">₹ 520</span>
          <span class="pv-add">+</span>
        </div>
        <div class="pv-item">
          <div>
            <b>Truffle Mushroom Pasta</b>
            <small>Creamy, wild mushrooms, truffle oil</small>
          </div>
          <span class="pv-price">₹ 420</span>
          <span class="pv-add">+</span>
        </div>
        <p class="pv-timer"><span class="pv-dot"></span> Served in 15 min — or it gets cheaper</p>
      </section>
    </div>
  `,
  styleUrl: './storefront-preview.component.scss',
})
export class StorefrontPreviewComponent {
  readonly tokens = input.required<ThemeTokens>();
  readonly name = input('Your restaurant');
  readonly tagline = input('');
  readonly logoUrl = input<string | null>(null);
  readonly coverUrl = input<string | null>(null);

  protected readonly vars = computed(() => tokensToCssVars(this.tokens()));
}

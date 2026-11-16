import { ChangeDetectionStrategy, Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';

import { ThemeService } from '../../core/theme/theme.service';

/**
 * Restaurant storefront shell (/r/:slug).
 *
 * Phase 1: the name is derived from the slug and the default theme is applied.
 * Phase 3/4: TenantContextService loads profile + branding from the public API and this
 * header becomes RestaurantHeaderComponent with the restaurant's logo and colours.
 * The WaitLess link on the right is permanent (PRD §2.2 "Do not remove").
 */
@Component({
  selector: 'wl-storefront-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './storefront-layout.component.html',
  styleUrl: './storefront-layout.component.scss',
})
export class StorefrontLayoutComponent implements OnDestroy {
  private readonly theme = inject(ThemeService);
  protected readonly slug = toSignal(inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('slug') ?? '')), {
    initialValue: '',
  });
  protected readonly name = computed(() =>
    this.slug()
      .split('-')
      .filter(Boolean)
      .map((w) => w[0].toUpperCase() + w.slice(1))
      .join(' '),
  );
  protected readonly initial = computed(() => this.name().charAt(0) || 'R');
  protected readonly menuOpen = signal(false);

  protected readonly nav = [
    { label: 'Home', path: '.' },
    { label: 'Menu', path: 'menu' },
    { label: 'Gallery', path: 'gallery' },
    { label: 'About Us', path: 'about' },
    { label: 'Reservations', path: 'reservations' },
    { label: 'Contact', path: 'contact' },
  ];

  constructor() {
    this.theme.reset(); // replaced by the restaurant's branding in Phase 3/4
  }

  ngOnDestroy(): void {
    this.theme.reset(); // never leak a restaurant's theme to the next page
  }
}

import { ChangeDetectionStrategy, Component, OnDestroy, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { AuthService } from '../../core/auth/auth.service';
import { CartService } from '../../core/ordering/cart.service';
import { SOCIAL_LABELS } from '../../core/storefront/storefront.models';
import { TenantContextService } from '../../core/storefront/tenant-context.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../shared/ui/state/state.components';
import { CallWaiterComponent } from '../../features/storefront/call-waiter/call-waiter.component';
import { UserMenuComponent } from '../../shared/ui/user-menu/user-menu.component';

/**
 * One reusable storefront for every restaurant (/r/:slug, PRD §2.2, §6, §20).
 * Everything restaurant-specific comes from TenantContextService; nothing is hard-coded.
 * The WaitLess link on the right is permanent (PRD §2.2 "Do not remove").
 */
@Component({
  selector: 'wl-storefront-layout',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    UserMenuComponent,
    LoadingStateComponent,
    ErrorStateComponent,
    CallWaiterComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './storefront-layout.component.html',
  styleUrl: './storefront-layout.component.scss',
})
export class StorefrontLayoutComponent implements OnDestroy {
  protected readonly ctx = inject(TenantContextService);
  protected readonly auth = inject(AuthService);
  protected readonly cart = inject(CartService);
  private readonly router = inject(Router);

  protected readonly slug = toSignal(inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('slug') ?? '')), {
    initialValue: '',
  });
  protected readonly r = this.ctx.restaurant;
  protected readonly initial = computed(() => (this.r()?.name ?? this.slug()).charAt(0).toUpperCase() || 'R');
  protected readonly year = new Date().getFullYear();
  protected readonly socialLabels = SOCIAL_LABELS;
  protected readonly menuOpen = signal(false);

  protected readonly nav = [
    { label: 'Home', path: '.' },
    { label: 'Menu', path: 'menu' },
    { label: 'Gallery', path: 'gallery' },
    { label: 'About Us', path: 'about' },
    { label: 'Reservations', path: 'reservations' },
    { label: 'Queue', path: 'queue' },
    { label: 'Contact', path: 'contact' },
  ];

  constructor() {
    // Switching /r/a → /r/b reuses this component: the effect swaps the whole tenant context.
    effect(() => {
      const slug = this.slug();
      if (slug) this.ctx.enter(slug);
    });
    this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => this.menuOpen.set(false));
  }

  ngOnDestroy(): void {
    this.ctx.leave(); // restores WaitLess branding; drops all restaurant data
  }
}

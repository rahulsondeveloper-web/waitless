import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { APP_CONFIG } from '../../../core/config/app-config';
import { ApiError } from '../../../core/http/api-error';
import { SiteContentService } from '../../../core/platform-admin/site-content.service';
import { StorefrontApi } from '../../../core/storefront/storefront.api';
import { RestaurantCardComponent } from '../../../shared/ui/restaurant-card/restaurant-card.component';

/** WaitLess landing page (PRD §2.1). Landing copy becomes Super Admin editable in Phase 11. */
@Component({
  selector: 'wl-home-page',
  imports: [RouterLink, ReactiveFormsModule, RestaurantCardComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './home.page.html',
  styleUrl: './home.page.scss',
})
export class HomePage {
  private readonly api = inject(StorefrontApi);
  private readonly router = inject(Router);
  private readonly fb = inject(NonNullableFormBuilder);
  protected readonly config = APP_CONFIG;

  protected readonly featured = toSignal(
    this.api.discover({ page_size: 6 }).pipe(
      map((p) => p.items),
      catchError(() => of([])),
    ),
    { initialValue: null },
  );

  /** Super Admin → Content (falls back to the built-in text below). */
  protected readonly site = inject(SiteContentService).content;
  private readonly defaultSteps = [
    { icon: 'search', title: 'Discover', text: 'Find restaurants near you and see if they are open right now.' },
    { icon: 'event_available', title: 'Book or queue', text: 'Reserve a table or join the digital queue from your phone.' },
    { icon: 'restaurant_menu', title: 'Order', text: 'Browse the menu and order — even before you arrive with a paid booking.' },
    { icon: 'timer', title: 'Served in 15', text: 'Late food? Your discount grows automatically, every 5 minutes.' },
  ];

  private readonly defaultFeatures = [
    { icon: 'storefront', title: 'Branded storefront', text: 'Your logo, colours and photos — your own app.' },
    { icon: 'groups', title: 'Digital queue', text: 'QR check-in, live position and table-ready alerts.' },
    { icon: 'event_seat', title: 'Reservations', text: 'Free or paid bookings with pre-orders.' },
    { icon: 'table_restaurant', title: 'Table management', text: 'Live floor map with colour-coded status.' },
    { icon: 'menu_book', title: 'Digital menu', text: 'Meal types, categories, variants and add-ons.' },
    { icon: 'soup_kitchen', title: 'Kitchen display', text: 'Tickets from accepted to served, in real time.' },
    { icon: 'inventory_2', title: 'Inventory', text: 'Recipes, stock movements and low-stock alerts.' },
    { icon: 'point_of_sale', title: 'Billing & POS', text: 'Split bills, UPI, cards and instant receipts.' },
  ];

  private readonly defaultBenefits = [
    'Turn tables faster with live queue and table status',
    'Fewer no-shows thanks to paid bookings with pre-orders',
    'A promise guests love: served in 15 minutes or it gets cheaper',
    'One dashboard for menu, kitchen, inventory and billing',
    'Your brand front and centre — guests feel they use your own app',
  ];

  protected readonly steps = computed(() => this.site()?.how_it_works.steps ?? this.defaultSteps);
  protected readonly features = computed(() => this.site()?.features.items ?? this.defaultFeatures);
  protected readonly benefits = computed(() => this.site()?.for_restaurants.benefits ?? this.defaultBenefits);

  constructor() {
    inject(SiteContentService).load();
  }

  protected search(q: string): void {
    void this.router.navigate(['/restaurants'], { queryParams: { q: q.trim() || null } });
  }

  // ---------- contact form ----------

  protected readonly contactForm = this.fb.group({
    name: ['', [Validators.required, Validators.minLength(2)]],
    email: ['', [Validators.required, Validators.email]],
    phone: [''],
    topic: ['general' as 'general' | 'restaurant_signup' | 'customer' | 'partnership' | 'other'],
    message: ['', [Validators.required, Validators.minLength(10)]],
    website: [''], // honeypot
  });
  protected readonly sending = signal(false);
  protected readonly sent = signal<string | null>(null);
  protected readonly sendError = signal<string | null>(null);

  protected sendContact(): void {
    if (this.contactForm.invalid) return this.contactForm.markAllAsTouched();
    this.sending.set(true);
    this.sendError.set(null);
    const v = this.contactForm.getRawValue();
    this.api.contact({ ...v, phone: v.phone.trim() || null }).subscribe({
      next: (r) => {
        this.sending.set(false);
        this.sent.set(r.message);
        this.contactForm.reset();
      },
      error: (e: ApiError) => {
        this.sending.set(false);
        this.sendError.set(e.code === 'RATE_LIMITED' ? 'You have sent several messages — please try again later.' : e.message);
      },
    });
  }
}

import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { Router, RouterLink } from '@angular/router';
import { catchError, debounceTime, distinctUntilChanged, map, merge, of, switchMap } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { CUISINES, RESTAURANT_TYPES, SlugAvailability } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';

/** PRD §4 restaurant registration. On success the owner is signed in and lands on the dashboard. */
@Component({
  selector: 'wl-register-restaurant-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatButtonModule,
    MatProgressSpinnerModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './register-restaurant.page.html',
  styleUrl: './register-restaurant.page.scss',
})
export class RegisterRestaurantPage {
  private readonly fb = inject(NonNullableFormBuilder);
  private readonly tenancy = inject(TenancyService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly restaurantTypes = RESTAURANT_TYPES;
  protected readonly cuisines = CUISINES;
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly slug = signal<SlugAvailability | null>(null);
  protected readonly checkingSlug = signal(false);
  protected readonly origin = typeof location !== 'undefined' ? location.host : 'waitless.com';

  protected readonly form = this.fb.group({
    restaurant_name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(120)]],
    restaurant_type: ['', Validators.required],
    cuisines: this.fb.control<string[]>([], Validators.required),
    number_of_branches: [1, [Validators.required, Validators.min(1), Validators.max(500)]],
    owner_name: ['', [Validators.required, Validators.minLength(2)]],
    email: ['', [Validators.required, Validators.email]],
    mobile: ['', [Validators.required, Validators.pattern(/^[+\d][\d\s-]{7,18}$/)]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    address: ['', [Validators.required, Validators.minLength(5)]],
    city: ['', [Validators.required, Validators.minLength(2)]],
    state: ['', [Validators.required, Validators.minLength(2)]],
    country: ['India', Validators.required],
    preferred_slug: [''],
  });

  constructor() {
    const c = this.form.controls;
    // Suggest a web address from name + city; check availability when the owner edits it.
    const suggest$ = merge(c.restaurant_name.valueChanges, c.city.valueChanges).pipe(
      map(() => ({ name: c.restaurant_name.value.trim(), city: c.city.value.trim() })),
      map((p) => (c.preferred_slug.dirty ? null : p)),
    );
    const edit$ = c.preferred_slug.valueChanges.pipe(map((slug) => ({ slug: slug.trim() })));

    merge(suggest$, edit$)
      .pipe(
        debounceTime(400),
        map((p) => (p && ('slug' in p ? p.slug : p.name.length >= 2) ? p : null)),
        distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
        switchMap((p) => {
          if (!p) return of(null);
          this.checkingSlug.set(true);
          return this.tenancy.slugAvailability(p).pipe(catchError(() => of(null)));
        }),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe((res) => {
        this.checkingSlug.set(false);
        this.slug.set(res);
        if (res && !c.preferred_slug.dirty) c.preferred_slug.setValue(res.slug, { emitEvent: false });
      });
  }

  protected useSuggestion(s: string): void {
    this.form.controls.preferred_slug.setValue(s);
    this.form.controls.preferred_slug.markAsDirty();
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.error.set('Please complete the highlighted fields.');
      return;
    }
    if (this.slug() && !this.slug()!.available) {
      this.error.set('That web address is taken — pick the suggestion or another one.');
      return;
    }
    const v = this.form.getRawValue();
    this.busy.set(true);
    this.error.set(null);
    this.tenancy
      .register({ ...v, preferred_slug: v.preferred_slug.trim() || null })
      .pipe(switchMap(() => this.auth.login(v.email, v.password)))
      .subscribe({
        next: () => void this.router.navigateByUrl('/restaurant-admin'),
        error: (e: ApiError) => {
          this.busy.set(false);
          const field = { EMAIL_TAKEN: 'email', PHONE_TAKEN: 'mobile', SLUG_TAKEN: 'preferred_slug' }[e.code];
          if (field) this.form.get(field)?.setErrors({ server: e.message });
          if (e.code === 'RATE_LIMITED') {
            const minutes = Math.ceil(Number(e.details['retry_after_seconds'] ?? 3600) / 60);
            this.error.set(`Too many registrations from this network. Please try again in ${minutes} min.`);
          } else {
            this.error.set(e.code === 'VALIDATION_ERROR' ? 'Some details are not valid. Please check the form.' : e.message);
          }
        },
      });
  }
}

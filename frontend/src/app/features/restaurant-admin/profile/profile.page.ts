import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormArray, FormGroup, NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Observable, forkJoin } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { HoursDay, Profile, SOCIAL_PLATFORMS, SocialLink, WEEKDAYS } from '../../../core/restaurant/restaurant.models';
import { RestaurantService } from '../../../core/restaurant/restaurant.service';
import { Branch, CUISINES, RESTAURANT_TYPES } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { LatLng, MapPickerComponent } from '../../../shared/ui/map-picker/map-picker.component';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { GuestWifiCardComponent } from './guest-wifi-card.component';

type Section = 'details' | 'location' | 'hours' | 'social';
const HTTPS = /^https:\/\/\S+$/i;

/** Restaurant Profile Management (PRD §5.1): details, location, opening hours, social links. */
@Component({
  selector: 'wl-profile-page',
  imports: [
    GuestWifiCardComponent,
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatChipsModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule,
    MapPickerComponent,
    LoadingStateComponent,
    ErrorStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './profile.page.html',
  styleUrl: './profile.page.scss',
})
export class ProfilePage implements OnInit {
  private readonly fb = inject(NonNullableFormBuilder);
  private readonly restaurant = inject(RestaurantService);
  private readonly tenancy = inject(TenancyService);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);

  protected readonly weekdays = WEEKDAYS;
  protected readonly types = RESTAURANT_TYPES;
  protected readonly platforms = SOCIAL_PLATFORMS;
  protected readonly loadError = signal<ApiError | null>(null);
  protected readonly loaded = signal(false);
  protected readonly saving = signal<Section | null>(null);
  protected readonly profile = signal<Profile | null>(null);
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly canManage = computed(() => this.auth.hasPermission('restaurant.profile.manage'));
  protected readonly canManageBranches = computed(() => this.auth.hasPermission('branches.manage'));
  protected readonly cuisineOptions = signal<string[]>([...CUISINES]);

  protected readonly details = this.fb.group({
    name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(120)]],
    restaurant_type: ['', Validators.required],
    cuisines: this.fb.control<string[]>([], Validators.required),
    short_description: ['', Validators.maxLength(300)],
    description: ['', Validators.maxLength(5000)],
    about_us: ['', Validators.maxLength(10000)],
    contact_phone: ['', Validators.pattern(/^$|^[+\d][\d\s-]{7,18}$/)],
    contact_email: ['', Validators.email],
    website: ['', Validators.pattern(/^$|^https:\/\/\S+$/i)],
  });

  protected readonly location = this.fb.group({
    name: ['', [Validators.required, Validators.minLength(2)]],
    address_line: ['', [Validators.required, Validators.minLength(5)]],
    city: ['', Validators.required],
    state: ['', Validators.required],
    country: ['', Validators.required],
    postal_code: [''],
    phone: ['', Validators.pattern(/^$|^[+\d][\d\s-]{7,18}$/)],
    lat: ['', [Validators.min(-90), Validators.max(90)]],
    lng: ['', [Validators.min(-180), Validators.max(180)]],
  });
  protected readonly pin = signal<LatLng | null>(null);

  protected readonly hours = this.fb.array(
    WEEKDAYS.map((_, weekday) =>
      this.fb.group({ weekday: [weekday], is_closed: [false], opens_at: ['11:00'], closes_at: ['23:00'] }),
    ),
  );

  protected readonly social = this.fb.array<FormGroup>([]);

  ngOnInit(): void {
    forkJoin({
      profile: this.restaurant.profile(),
      branches: this.tenancy.branches(),
      social: this.restaurant.socialLinks(),
    }).subscribe({
      next: ({ profile, branches, social }) => {
        this.setProfile(profile);
        this.branches.set(branches);
        social.forEach((s) => this.addSocial(s));
        this.selectBranch(branches.find((b) => b.is_primary)?.id ?? branches[0]?.id ?? null);
        if (!this.canManage()) this.details.disable();
        this.loaded.set(true);
      },
      error: (e: ApiError) => this.loadError.set(e),
    });
  }

  // ---------- details ----------

  private setProfile(p: Profile): void {
    this.profile.set(p);
    this.cuisineOptions.update((opts) => [...new Set([...opts, ...p.cuisines])]);
    this.details.reset({
      name: p.name,
      restaurant_type: p.restaurant_type,
      cuisines: p.cuisines,
      short_description: p.short_description,
      description: p.description,
      about_us: p.about_us,
      contact_phone: p.contact_phone ?? '',
      contact_email: p.contact_email ?? '',
      website: p.website ?? '',
    });
  }

  protected saveDetails(): void {
    if (this.details.invalid) return this.details.markAllAsTouched();
    const v = this.details.getRawValue();
    this.save('details', this.restaurant.updateProfile({
      ...v,
      contact_phone: v.contact_phone.trim() || null,
      contact_email: v.contact_email.trim() || null,
      website: v.website.trim() || null,
    }), (p) => this.setProfile(p as Profile));
  }

  // ---------- location ----------

  protected selectBranch(id: string | null): void {
    this.branchId.set(id);
    const b = this.branches().find((x) => x.id === id);
    if (!b) return;
    this.location.reset({
      name: b.name,
      address_line: b.address_line,
      city: b.city,
      state: b.state,
      country: b.country,
      postal_code: b.postal_code ?? '',
      phone: b.phone ?? '',
      lat: b.lat ?? '',
      lng: b.lng ?? '',
    });
    this.pin.set(b.lat && b.lng ? { lat: +b.lat, lng: +b.lng } : null);
    if (!this.canManageBranches()) this.location.disable();
    this.loadHours(b.id);
  }

  protected onPicked(p: LatLng): void {
    this.location.patchValue({ lat: String(p.lat), lng: String(p.lng) });
    this.location.markAsDirty();
  }

  protected onCoordsTyped(): void {
    const { lat, lng } = this.location.getRawValue();
    if (lat !== '' && lng !== '' && !isNaN(+lat) && !isNaN(+lng)) this.pin.set({ lat: +lat, lng: +lng });
  }

  protected saveLocation(): void {
    const id = this.branchId();
    if (!id) return;
    if (this.location.invalid) return this.location.markAllAsTouched();
    const v = this.location.getRawValue();
    this.save(
      'location',
      this.restaurant.updateBranch(id, {
        ...v,
        postal_code: v.postal_code.trim() || null,
        phone: v.phone.trim() || null,
        lat: v.lat === '' ? null : String(v.lat),
        lng: v.lng === '' ? null : String(v.lng),
      }),
      (b) => this.branches.update((all) => all.map((x) => (x.id === id ? (b as Branch) : x))),
    );
  }

  // ---------- hours ----------

  private loadHours(branchId: string): void {
    this.restaurant.hours(branchId).subscribe((h) => {
      if (h.days.length === 7) {
        this.hours.reset(
          h.days.map((d) => ({
            weekday: d.weekday,
            is_closed: d.is_closed,
            opens_at: d.opens_at?.slice(0, 5) ?? '11:00',
            closes_at: d.closes_at?.slice(0, 5) ?? '23:00',
          })),
        );
      }
      if (!this.canManage()) this.hours.disable();
    });
  }

  protected copyMondayToAll(): void {
    const monday = this.hours.at(0).getRawValue();
    this.hours.controls.forEach((c, i) => i > 0 && c.patchValue({ ...monday, weekday: i }));
    this.hours.markAsDirty();
  }

  protected saveHours(): void {
    const id = this.branchId();
    if (!id) return;
    const days: HoursDay[] = this.hours.getRawValue().map((d) => ({
      weekday: d.weekday,
      is_closed: d.is_closed,
      opens_at: d.is_closed ? null : d.opens_at,
      closes_at: d.is_closed ? null : d.closes_at,
    }));
    const bad = days.find((d) => !d.is_closed && (!d.opens_at || !d.closes_at || d.opens_at === d.closes_at));
    if (bad) {
      this.snack.open(`Check the times for ${WEEKDAYS[bad.weekday]}.`, 'OK', { duration: 4000 });
      return;
    }
    this.save('hours', this.restaurant.setHours(id, days), () => this.hours.markAsPristine());
  }

  // ---------- social ----------

  protected addSocial(link?: SocialLink): void {
    this.social.push(
      this.fb.group({
        platform: [link?.platform ?? this.nextPlatform(), Validators.required],
        url: [link?.url ?? 'https://', [Validators.required, Validators.pattern(HTTPS)]],
      }),
    );
    if (link) this.social.markAsPristine();
  }

  protected removeSocial(i: number): void {
    this.social.removeAt(i);
    this.social.markAsDirty();
  }

  private nextPlatform(): string {
    const used = new Set(this.social.getRawValue().map((s) => s['platform']));
    return this.platforms.find((p) => !used.has(p)) ?? 'other';
  }

  protected saveSocial(): void {
    if (this.social.invalid) return this.social.markAllAsTouched();
    const links = this.social.getRawValue() as SocialLink[];
    if (new Set(links.map((l) => l.platform)).size !== links.length) {
      this.snack.open('Each platform can be added once.', 'OK', { duration: 4000 });
      return;
    }
    this.save('social', this.restaurant.setSocialLinks(links), () => this.social.markAsPristine());
  }

  protected socialRows(): FormGroup[] {
    return (this.social as FormArray<FormGroup>).controls;
  }

  // ---------- shared ----------

  private save<T>(section: Section, obs: Observable<T>, done: (v: T) => void): void {
    this.saving.set(section);
    obs.subscribe({
      next: (v) => {
        this.saving.set(null);
        done(v);
        this.snack.open('Saved', undefined, { duration: 2000 });
      },
      error: (e: ApiError) => {
        this.saving.set(null);
        const detail = (e.details['errors'] as { msg: string }[] | undefined)?.[0]?.msg;
        this.snack.open(detail ? `${e.message} ${detail}` : e.message, 'Dismiss', { duration: 6000 });
      },
    });
  }
}

import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { filter, forkJoin } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { Branding, BrandingColors, Profile } from '../../../core/restaurant/restaurant.models';
import { RestaurantService } from '../../../core/restaurant/restaurant.service';
import { ButtonStyle, ThemeMode, brandingToTokens, contrastRatio } from '../../../core/theme/theme.tokens';
import { ConfirmDialogComponent, ConfirmData } from '../../../shared/ui/confirm-dialog/confirm-dialog.component';
import { checkImageFile, takeFile } from '../../../shared/ui/image-check';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { StorefrontPreviewComponent } from '../../../shared/ui/storefront-preview/storefront-preview.component';

type ColorKey = keyof BrandingColors;

const COLOR_FIELDS: { key: ColorKey; label: string; hint: string }[] = [
  { key: 'primary', label: 'Primary', hint: 'Buttons, links, highlights' },
  { key: 'secondary', label: 'Secondary', hint: 'Status and success accents' },
  { key: 'accent', label: 'Accent', hint: 'Badges like "Chef\'s special"' },
  { key: 'background', label: 'Background', hint: 'Page background' },
  { key: 'surface', label: 'Cards', hint: 'Cards and panels' },
  { key: 'text', label: 'Text', hint: 'Main text colour' },
];

/** Branding & theme (PRD §5.2, §5.4): logo, cover, colours, button style, mode — with live preview. */
@Component({
  selector: 'wl-branding-page',
  imports: [
    MatButtonModule,
    MatButtonToggleModule,
    MatIconModule,
    MatProgressSpinnerModule,
    StorefrontPreviewComponent,
    LoadingStateComponent,
    ErrorStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './branding.page.html',
  styleUrl: './branding.page.scss',
})
export class BrandingPage implements OnInit {
  private readonly restaurant = inject(RestaurantService);
  private readonly snack = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly auth = inject(AuthService);
  protected readonly canEdit = computed(() => this.auth.hasPermission('restaurant.branding.manage'));

  protected readonly fields = COLOR_FIELDS;
  protected readonly loadError = signal<ApiError | null>(null);
  protected readonly saved = signal<Branding | null>(null);
  protected readonly profile = signal<Profile | null>(null);
  protected readonly busy = signal<'save' | 'reset' | 'logo' | 'cover' | null>(null);

  // Editable state
  protected readonly colors = signal<BrandingColors>({});
  protected readonly buttonStyle = signal<ButtonStyle>('pill');
  protected readonly mode = signal<ThemeMode>('light');

  protected readonly preview = computed(() =>
    brandingToTokens({ tokens: this.colors(), button_style: this.buttonStyle(), mode: this.mode() }),
  );
  protected readonly dirty = computed(() => {
    const s = this.saved();
    if (!s) return false;
    return (
      JSON.stringify(sortKeys(this.colors())) !== JSON.stringify(sortKeys(s.tokens)) ||
      this.buttonStyle() !== s.button_style ||
      this.mode() !== s.mode
    );
  });
  protected readonly warnings = computed(() => {
    const t = this.preview();
    const w: string[] = [];
    if (contrastRatio(t.text, t.background) < 4.5) w.push('Text is hard to read on the background (contrast below 4.5:1).');
    if (contrastRatio('#ffffff', t.primary) < 3) w.push('White button text is hard to read on the primary colour.');
    return w;
  });

  /** The owner's colour, or the effective default for the current mode. */
  protected valueFor(key: ColorKey): string {
    return this.colors()[key] ?? this.preview()[key];
  }

  ngOnInit(): void {
    forkJoin({ branding: this.restaurant.branding(), profile: this.restaurant.profile() }).subscribe({
      next: ({ branding, profile }) => {
        this.applySaved(branding);
        this.profile.set(profile);
      },
      error: (e: ApiError) => this.loadError.set(e),
    });
  }

  protected setColor(key: ColorKey, value: string): void {
    if (/^#[0-9a-f]{6}$/i.test(value)) this.colors.update((c) => ({ ...c, [key]: value.toLowerCase() }));
  }

  protected clearColor(key: ColorKey): void {
    this.colors.update((c) => {
      const next = { ...c };
      delete next[key];
      return next;
    });
  }

  protected save(): void {
    this.busy.set('save');
    this.restaurant
      .updateBranding({ tokens: this.colors(), button_style: this.buttonStyle(), mode: this.mode() })
      .subscribe({
        next: (b) => {
          this.applySaved(b);
          this.busy.set(null);
          this.snack.open('Theme saved — your storefront uses it now.', undefined, { duration: 2500 });
        },
        error: (e: ApiError) => this.fail(e),
      });
  }

  protected reset(): void {
    const data: ConfirmData = {
      title: 'Reset to the default theme?',
      message: 'Colours, button style and mode go back to the WaitLess default. Your logo and cover stay.',
      confirm: 'Reset theme',
    };
    this.dialog
      .open(ConfirmDialogComponent, { data, width: '420px' })
      .afterClosed()
      .pipe(filter(Boolean))
      .subscribe(() => {
        this.busy.set('reset');
        this.restaurant.resetBranding().subscribe({
          next: (b) => {
            this.applySaved(b);
            this.busy.set(null);
            this.snack.open('Default theme restored.', undefined, { duration: 2500 });
          },
          error: (e: ApiError) => this.fail(e),
        });
      });
  }

  protected uploadLogo(event: Event): void {
    const file = takeFile(event);
    const problem = checkImageFile(file);
    if (problem) return void this.snack.open(problem, 'OK', { duration: 4000 });
    this.busy.set('logo');
    this.restaurant.uploadLogo(file!).subscribe({
      next: (b) => {
        this.saved.update((s) => (s ? { ...s, logo_url: b.logo_url, version: b.version } : b));
        this.busy.set(null);
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  protected removeLogo(): void {
    this.busy.set('logo');
    this.restaurant.removeLogo().subscribe({
      next: (b) => {
        this.saved.update((s) => (s ? { ...s, logo_url: b.logo_url } : b));
        this.busy.set(null);
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  protected uploadCover(event: Event): void {
    const file = takeFile(event);
    const problem = checkImageFile(file);
    if (problem) return void this.snack.open(problem, 'OK', { duration: 4000 });
    this.busy.set('cover');
    this.restaurant.uploadCover(file!).subscribe({
      next: (p) => {
        this.profile.set(p);
        this.busy.set(null);
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  protected removeCover(): void {
    this.busy.set('cover');
    this.restaurant.removeCover().subscribe({
      next: (p) => {
        this.profile.set(p);
        this.busy.set(null);
      },
      error: (e: ApiError) => this.fail(e),
    });
  }

  private applySaved(b: Branding): void {
    this.saved.set(b);
    this.colors.set({ ...b.tokens });
    this.buttonStyle.set(b.button_style);
    this.mode.set(b.mode);
  }

  private fail(e: ApiError): void {
    this.busy.set(null);
    this.snack.open(e.message, 'Dismiss', { duration: 6000 });
  }
}

function sortKeys(o: object): [string, unknown][] {
  return Object.entries(o).sort(([a], [b]) => a.localeCompare(b));
}

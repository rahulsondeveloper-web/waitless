import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';

import {
  Branding,
  DEFAULT_THEME,
  ThemeTokens,
  brandingToTokens,
  sanitizeTokens,
  tokensToCssVars,
} from './theme.tokens';

/**
 * Applies theme tokens as CSS variables on <html>.
 * - Platform pages and admin use the default (WaitLess) theme.
 * - A storefront calls applyBranding(restaurant.branding) on enter and reset() on leave.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly doc = inject(DOCUMENT);
  private readonly _tokens = signal<ThemeTokens>({ ...DEFAULT_THEME });
  readonly tokens = this._tokens.asReadonly();

  apply(tokens: Partial<ThemeTokens> | null | undefined): void {
    const clean = sanitizeTokens(tokens);
    const root = this.doc.documentElement;
    for (const [name, value] of Object.entries(tokensToCssVars(clean))) {
      root.style.setProperty(name, value);
    }
    root.dataset['wlMode'] = clean.mode;
    root.style.colorScheme = clean.mode === 'dark' ? 'dark' : 'light';
    this._tokens.set(clean);
  }

  /** Restaurant branding → full theme. "auto" follows the guest's device setting. */
  applyBranding(branding: Pick<Branding, 'tokens' | 'button_style' | 'mode'> | null | undefined): void {
    if (!branding) return this.reset();
    const prefersDark =
      branding.mode === 'auto' && typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches;
    this.apply(brandingToTokens({ ...branding, mode: branding.mode === 'auto' ? (prefersDark ? 'dark' : 'light') : branding.mode }));
  }

  reset(): void {
    this.apply(DEFAULT_THEME);
  }
}

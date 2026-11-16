import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';

import { DEFAULT_THEME, ThemeTokens, sanitizeTokens, tokensToCssVars } from './theme.tokens';

/**
 * Applies theme tokens as CSS variables on <html>.
 * - Platform pages and admin use the default (WaitLess) theme.
 * - A storefront calls apply(restaurant.branding) on enter and reset() on leave.
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
    this._tokens.set(clean);
  }

  reset(): void {
    this.apply(DEFAULT_THEME);
  }
}

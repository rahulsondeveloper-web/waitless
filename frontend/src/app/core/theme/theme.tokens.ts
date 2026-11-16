/**
 * Theme tokens — the contract between restaurant branding (API) and storefront styles.
 * Every storefront style reads only these CSS variables, so a restaurant's theme changes
 * without rebuilding Angular (PRD §2.2, §5.4).
 *
 * DEFAULT_THEME is the "Restaurant Remelle" template (decision D1). Owners can reset to it.
 */
export type ButtonStyle = 'pill' | 'rounded' | 'square';
export type ThemeMode = 'light' | 'dark' | 'auto';

export interface ThemeTokens {
  primary: string;
  primaryDark: string;
  primarySoft: string;
  secondary: string;
  accent: string;
  background: string;
  surface: string;
  surfaceAlt: string;
  line: string;
  text: string;
  textSoft: string;
  muted: string;
  buttonStyle: ButtonStyle;
  mode: ThemeMode;
}

export const DEFAULT_THEME: Readonly<ThemeTokens> = Object.freeze({
  primary: '#b9553a',
  primaryDark: '#9a4330',
  primarySoft: '#f3dfd5',
  secondary: '#4e7a4a',
  accent: '#e0a53b',
  background: '#f7efe4',
  surface: '#fffaf3',
  surfaceAlt: '#efe3d2',
  line: '#e6d8c5',
  text: '#2b2522',
  textSoft: '#4a403a',
  muted: '#84776d',
  buttonStyle: 'pill',
  mode: 'light',
});

const RADIUS: Record<ButtonStyle, string> = { pill: '999px', rounded: '10px', square: '2px' };

/** Maps tokens to CSS custom properties (kebab-case, `--wl-` prefix). */
export function tokensToCssVars(t: ThemeTokens): Record<string, string> {
  return {
    '--wl-primary': t.primary,
    '--wl-primary-dark': t.primaryDark,
    '--wl-primary-soft': t.primarySoft,
    '--wl-secondary': t.secondary,
    '--wl-accent': t.accent,
    '--wl-bg': t.background,
    '--wl-surface': t.surface,
    '--wl-surface-alt': t.surfaceAlt,
    '--wl-line': t.line,
    '--wl-text': t.text,
    '--wl-text-soft': t.textSoft,
    '--wl-muted': t.muted,
    '--wl-btn-radius': RADIUS[t.buttonStyle],
  };
}

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

/** Accepts partial/untrusted branding from the API; anything invalid falls back to the default. */
export function sanitizeTokens(input: Partial<ThemeTokens> | null | undefined): ThemeTokens {
  const out: ThemeTokens = { ...DEFAULT_THEME };
  if (!input) return out;
  for (const key of Object.keys(DEFAULT_THEME) as (keyof ThemeTokens)[]) {
    const v = input[key];
    if (typeof v !== 'string') continue;
    if (key === 'buttonStyle') {
      if (v in RADIUS) out.buttonStyle = v as ButtonStyle;
    } else if (key === 'mode') {
      if (v === 'light' || v === 'dark' || v === 'auto') out.mode = v;
    } else if (HEX.test(v)) {
      (out as unknown as Record<string, string>)[key] = v.toLowerCase();
    }
  }
  return out;
}

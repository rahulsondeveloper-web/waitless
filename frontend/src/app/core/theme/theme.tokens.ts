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

// ---------- restaurant branding → full token set ----------

/** Colours an owner edits (backend BrandingTokens). Everything else is derived. */
export interface BrandingColors {
  primary?: string;
  secondary?: string;
  accent?: string;
  background?: string;
  surface?: string;
  text?: string;
}

export interface Branding {
  logo_url: string | null;
  tokens: BrandingColors;
  button_style: ButtonStyle;
  mode: ThemeMode;
  version: number;
  is_default: boolean;
}

export const DARK_BASE: Readonly<ThemeTokens> = Object.freeze({
  ...DEFAULT_THEME,
  primary: '#d9714f',
  background: '#1c1815',
  surface: '#26201c',
  surfaceAlt: '#2f2823',
  line: '#3d342e',
  text: '#f3ebe1',
  textSoft: '#ddd2c6',
  muted: '#a99c90',
  mode: 'dark',
});

/** Mix two hex colours; weight = share of `b` (0..1). */
export function mix(a: string, b: string, weight: number): string {
  const pa = parseHex(a);
  const pb = parseHex(b);
  const c = pa.map((v, i) => Math.round(v * (1 - weight) + pb[i] * weight));
  return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
}

function parseHex(hex: string): [number, number, number] {
  let h = hex.replace('#', '');
  if (h.length === 3) h = [...h].map((ch) => ch + ch).join('');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** WCAG relative-luminance contrast ratio (1..21). */
export function contrastRatio(a: string, b: string): number {
  const lum = (hex: string) => {
    const [r, g, bl] = parseHex(hex).map((v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * Builds the complete storefront theme from what the owner chose. Unset colours come from the
 * default (Remelle) theme — or its dark variant — and shades (hover, soft tint, borders, muted text)
 * are derived so a single brand colour still yields a coherent theme.
 */
export function brandingToTokens(b: Pick<Branding, 'tokens' | 'button_style' | 'mode'> | null | undefined): ThemeTokens {
  const base = b?.mode === 'dark' ? DARK_BASE : DEFAULT_THEME;
  const c = b?.tokens ?? {};
  const pick = (v: string | undefined, fallback: string) => (v && HEX.test(v) ? v.toLowerCase() : fallback);

  const primary = pick(c.primary, base.primary);
  const background = pick(c.background, base.background);
  const text = pick(c.text, base.text);
  const surface = pick(c.surface, c.background ? mix(background, '#ffffff', base.mode === 'dark' ? 0.04 : 0.5) : base.surface);
  return sanitizeTokens({
    primary,
    primaryDark: c.primary ? mix(primary, '#000000', 0.18) : base.primaryDark,
    primarySoft: c.primary ? mix(primary, background, 0.82) : base.primarySoft,
    secondary: pick(c.secondary, base.secondary),
    accent: pick(c.accent, base.accent),
    background,
    surface,
    surfaceAlt: c.background || c.primary ? mix(background, primary, 0.07) : base.surfaceAlt,
    line: c.background || c.text ? mix(background, text, 0.13) : base.line,
    text,
    textSoft: c.text || c.background ? mix(text, background, 0.15) : base.textSoft,
    muted: c.text || c.background ? mix(text, background, 0.45) : base.muted,
    buttonStyle: b?.button_style ?? 'pill',
    mode: b?.mode ?? 'light',
  });
}

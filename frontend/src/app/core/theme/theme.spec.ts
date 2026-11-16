import { TestBed } from '@angular/core/testing';

import { ThemeService } from './theme.service';
import {
  DARK_BASE,
  DEFAULT_THEME,
  brandingToTokens,
  contrastRatio,
  mix,
  sanitizeTokens,
  tokensToCssVars,
} from './theme.tokens';

describe('restaurant branding → theme', () => {
  it('mixes colours', () => {
    expect(mix('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(mix('#b9553a', '#b9553a', 0.3)).toBe('#b9553a');
  });

  it('computes WCAG contrast', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0);
    expect(contrastRatio('#777777', '#777777')).toBeCloseTo(1, 5);
  });

  it('empty branding = the default Remelle theme', () => {
    expect(brandingToTokens({ tokens: {}, button_style: 'pill', mode: 'light' })).toEqual(DEFAULT_THEME);
  });

  it('derives hover and soft shades from a single primary colour', () => {
    const t = brandingToTokens({ tokens: { primary: '#0A7C86' }, button_style: 'rounded', mode: 'light' });
    expect(t.primary).toBe('#0a7c86');
    expect(t.primaryDark).not.toBe(DEFAULT_THEME.primaryDark);
    expect(contrastRatio(t.primaryDark, '#ffffff')).toBeGreaterThan(contrastRatio(t.primary, '#ffffff'));
    expect(t.background).toBe(DEFAULT_THEME.background);
    expect(t.buttonStyle).toBe('rounded');
  });

  it('dark mode starts from the dark base', () => {
    const t = brandingToTokens({ tokens: {}, button_style: 'pill', mode: 'dark' });
    expect(t.background).toBe(DARK_BASE.background);
    expect(contrastRatio(t.text, t.background)).toBeGreaterThan(7);
  });

  it('ignores invalid colours from the API', () => {
    const t = brandingToTokens({ tokens: { primary: 'javascript:alert(1)' }, button_style: 'pill', mode: 'light' });
    expect(t.primary).toBe(DEFAULT_THEME.primary);
  });
});

describe('theme tokens', () => {
  it('falls back to the default theme for missing or invalid values', () => {
    const t = sanitizeTokens({ primary: '#123ABC', secondary: 'red; background:url(x)', buttonStyle: 'bogus' as never });
    expect(t.primary).toBe('#123abc');
    expect(t.secondary).toBe(DEFAULT_THEME.secondary);
    expect(t.buttonStyle).toBe(DEFAULT_THEME.buttonStyle);
  });

  it('returns the default theme for null input', () => {
    expect(sanitizeTokens(null)).toEqual(DEFAULT_THEME);
  });

  it('maps button style to a radius variable', () => {
    expect(tokensToCssVars({ ...DEFAULT_THEME, buttonStyle: 'square' })['--wl-btn-radius']).toBe('2px');
  });
});

describe('ThemeService', () => {
  let service: ThemeService;
  const root = document.documentElement;

  beforeEach(() => {
    service = TestBed.inject(ThemeService);
  });

  it('applies restaurant colours as CSS variables', () => {
    service.apply({ primary: '#0a7c86' });
    expect(root.style.getPropertyValue('--wl-primary')).toBe('#0a7c86');
    expect(service.tokens().primary).toBe('#0a7c86');
  });

  it('reset() restores the default (Remelle) theme', () => {
    service.apply({ primary: '#0a7c86', background: '#000000' });
    service.reset();
    expect(root.style.getPropertyValue('--wl-primary')).toBe(DEFAULT_THEME.primary);
    expect(root.style.getPropertyValue('--wl-bg')).toBe(DEFAULT_THEME.background);
    expect(service.tokens()).toEqual(DEFAULT_THEME);
  });
});

import { TestBed } from '@angular/core/testing';

import { ThemeService } from './theme.service';
import { DEFAULT_THEME, sanitizeTokens, tokensToCssVars } from './theme.tokens';

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

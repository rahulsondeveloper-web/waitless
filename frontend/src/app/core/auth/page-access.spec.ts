import { PAGE_ACCESS, canOpenPage, pageKey } from './page-access';

describe('page access by role', () => {
  const role = (...perms: string[]) => (p: string) => perms.includes(p);

  it('opens a page when the role has any of its permissions', () => {
    expect(canOpenPage('kitchen', role('kitchen.operate'))).toBe(true);
    expect(canOpenPage('billing', role('payments.collect'))).toBe(true);
    expect(canOpenPage('reports', role('kitchen.operate'))).toBe(false);
  });

  it('keeps Dashboard and Settings open to every staff member', () => {
    expect(canOpenPage('.', role())).toBe(true);
    expect(canOpenPage('settings', role())).toBe(true);
  });

  it('guards sub-pages by their parent page', () => {
    expect(pageKey('tables/qr')).toBe('tables');
    expect(canOpenPage('tables/qr', role('menu.manage'))).toBe(false);
    expect(canOpenPage('tables/qr', role('tables.configure'))).toBe(true);
  });

  it('gives every guarded page at least one permission', () => {
    for (const v of Object.values(PAGE_ACCESS)) expect(v.perms.length).toBeGreaterThan(0);
  });
});

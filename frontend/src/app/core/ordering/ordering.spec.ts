import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { PublicItem } from '../storefront/storefront.models';
import { TenantContextService } from '../storefront/tenant-context.service';
import { CartService } from './cart.service';
import { inWindow, itemPrice, unavailableReason, windowsText } from './ordering.service';

const dish = (over: Partial<PublicItem> = {}): PublicItem => ({
  id: 'd1',
  name: 'Paneer Tikka',
  description: '',
  image_url: null,
  price: '250.00',
  food_class: 'veg',
  spice_level: 1,
  allergens: [],
  prep_minutes: 15,
  is_bestseller: false,
  is_todays_special: false,
  is_available: true,
  subcategory: null,
  tax_pct: '5.00',
  tags: [],
  variants: [],
  addon_groups: [],
  availability: [],
  branch_overrides: [],
  ...over,
});

describe('menu helpers', () => {
  // Wednesday 18 Nov 2026, 13:00 in India = 07:30 UTC
  const wedLunch = new Date('2026-11-18T07:30:00Z');

  it('uses the branch price override and the cheapest size', () => {
    const d = dish({ branch_overrides: [{ branch_id: 'b2', is_available: true, price_override: '199.00' }] });
    expect(itemPrice(d, 'b1')).toBe(250);
    expect(itemPrice(d, 'b2')).toBe(199);
    const sized = dish({ variants: [{ id: 'v1', name: 'Half', price: '180' }, { id: 'v2', name: 'Full', price: '320' }] });
    expect(itemPrice(sized, 'b1')).toBe(180);
  });

  it('checks serving windows in the branch time zone', () => {
    const lunch = [{ weekday: 2, from_time: '12:00:00', to_time: '15:00:00' }];
    expect(inWindow(lunch, 'Asia/Kolkata', wedLunch)).toBe(true);
    expect(inWindow(lunch, 'UTC', wedLunch)).toBe(false); // 07:30 there
    expect(unavailableReason(dish({ availability: lunch }), 'b1', 'Asia/Kolkata', wedLunch)).toBeNull();
    expect(unavailableReason(dish({ availability: lunch }), 'b1', 'UTC', wedLunch)).toBe('Served Wed 12:00–15:00');
  });

  it('explains sold out and branch-hidden dishes', () => {
    expect(unavailableReason(dish({ is_available: false }), 'b1', 'Asia/Kolkata')).toBe('Sold out');
    const hidden = dish({ branch_overrides: [{ branch_id: 'b1', is_available: false, price_override: null }] });
    expect(unavailableReason(hidden, 'b1', 'Asia/Kolkata')).toBe('Not served at this branch');
    expect(windowsText([0, 1, 2, 3, 4, 5, 6].map((d) => ({ weekday: d, from_time: '08:00:00', to_time: '11:00:00' })))).toBe(
      '08:00–11:00',
    );
  });
});

describe('CartService', () => {
  const slug = signal<string | null>('urban-bites');
  let cart: CartService;

  beforeEach(() => {
    localStorage.clear();
    slug.set('urban-bites');
    TestBed.configureTestingModule({ providers: [{ provide: TenantContextService, useValue: { slug } }] });
    cart = TestBed.inject(CartService);
    TestBed.tick();
  });

  const line = {
    menu_item_id: 'd1',
    name: 'Paneer Tikka',
    food_class: 'veg',
    variant_id: null,
    variant_name: null,
    addon_ids: [],
    addon_names: [],
    unit_price: 250,
    tax_pct: 5,
    quantity: 2,
    instructions: '',
  };

  it('merges identical lines and totals with tax', () => {
    cart.add(line);
    cart.add({ ...line, quantity: 1 });
    cart.add({ ...line, instructions: 'no onion', quantity: 1 });
    expect(cart.lines().length).toBe(2);
    expect(cart.count()).toBe(4);
    expect(cart.subtotal()).toBe(1000);
    expect(cart.tax()).toBe(50);
    expect(cart.total()).toBe(1050);
  });

  it('keeps one cart per restaurant: switching never carries dishes across', () => {
    cart.add(line);
    cart.setTableToken('token-a');
    slug.set('remelle');
    TestBed.tick();
    expect(cart.lines()).toEqual([]);
    expect(cart.tableToken()).toBeNull();
    cart.add({ ...line, menu_item_id: 'r1', name: 'Croissant' });
    slug.set('urban-bites');
    TestBed.tick();
    expect(cart.lines().map((l) => l.name)).toEqual(['Paneer Tikka']);
    expect(cart.tableToken()).toBe('token-a');
  });

  it('removes a line at quantity 0 and maps to the API shape', () => {
    cart.add(line);
    expect(cart.toOrder()).toEqual([{ menu_item_id: 'd1', variant_id: null, addon_ids: [], quantity: 2, instructions: '' }]);
    cart.setQuantity(cart.lines()[0].key, 0);
    expect(cart.count()).toBe(0);
  });
});

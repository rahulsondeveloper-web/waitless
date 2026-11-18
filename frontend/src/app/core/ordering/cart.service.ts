import { Injectable, computed, effect, inject, signal } from '@angular/core';

import { TenantContextService } from '../storefront/tenant-context.service';
import { OrderLineIn } from './ordering.service';

/**
 * The guest's cart for the restaurant currently shown (PRD §13, §20 isolation).
 * - One cart per restaurant slug (stored in this browser only); switching restaurants switches carts,
 *   so dishes from A can never be sent to B.
 * - Prices here are a preview: the server re-prices everything when the order is placed.
 * - The table token (code + PIN) and the "pre-order for booking" choice are also kept per slug.
 */

export interface CartLine {
  key: string; // item + variant + add-ons + instructions
  menu_item_id: string;
  name: string;
  food_class: string;
  variant_id: string | null;
  variant_name: string | null;
  addon_ids: string[];
  addon_names: string[];
  unit_price: number; // preview
  tax_pct: number;
  quantity: number;
  instructions: string;
}

const MAX_QTY = 50;

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / storage full: the cart still works for this page view */
  }
}

@Injectable({ providedIn: 'root' })
export class CartService {
  private readonly ctx = inject(TenantContextService);
  private readonly _lines = signal<CartLine[]>([]);
  private readonly _table = signal<string | null>(null);
  private readonly _preorder = signal<string | null>(null);
  private readonly _name = signal('');
  private loadedFor: string | null = null;

  readonly lines = this._lines.asReadonly();
  /** Table token from "Have an order ID?" (code + PIN). */
  readonly tableToken = this._table.asReadonly();
  /** Reservation id when the guest pre-orders for a paid booking. */
  readonly preorderFor = this._preorder.asReadonly();
  /** "Riya" — shown with this guest's dishes to the table, kitchen and staff (never on the invoice). */
  readonly guestName = this._name.asReadonly();
  private readonly _ended = signal<EndedVisit | null>(null);
  /** The visit that just ended (paid and closed) — memory only, gone on reload. */
  readonly endedVisit = this._ended.asReadonly();
  readonly count = computed(() => this._lines().reduce((n, l) => n + l.quantity, 0));
  readonly subtotal = computed(() => round(this._lines().reduce((s, l) => s + l.unit_price * l.quantity, 0)));
  readonly tax = computed(() =>
    round(this._lines().reduce((s, l) => s + round(l.unit_price * l.quantity * (l.tax_pct / 100)), 0)),
  );
  readonly total = computed(() => round(this.subtotal() + this.tax()));

  constructor() {
    // Follow the restaurant in view: load its own cart, never another restaurant's.
    effect(() => {
      const slug = this.ctx.slug();
      if (slug === this.loadedFor) return;
      this.loadedFor = slug;
      this._lines.set(slug ? read<CartLine[]>(this.key(slug, 'cart'), []) : []);
      this._table.set(slug ? read<string | null>(this.key(slug, 'table'), null) : null);
      this._preorder.set(slug ? read<string | null>(this.key(slug, 'preorder'), null) : null);
      this._name.set(slug ? read<string>(this.key(slug, 'name'), '') : '');
    });
  }

  add(line: Omit<CartLine, 'key'>): void {
    const key = [line.menu_item_id, line.variant_id ?? '', [...line.addon_ids].sort().join('.'), line.instructions.trim()].join('|');
    const lines = [...this._lines()];
    const existing = lines.find((l) => l.key === key);
    if (existing) existing.quantity = Math.min(MAX_QTY, existing.quantity + line.quantity);
    else lines.push({ ...line, key, quantity: Math.min(MAX_QTY, line.quantity) });
    this.save(lines.map((l) => ({ ...l })));
  }

  setQuantity(key: string, quantity: number): void {
    const q = Math.max(0, Math.min(MAX_QTY, Math.floor(quantity)));
    this.save(this._lines().map((l) => (l.key === key ? { ...l, quantity: q } : l)).filter((l) => l.quantity > 0));
  }

  clear(): void {
    this.save([]);
  }

  /**
   * The table's bill is paid and the visit closed: forget everything this browser kept for it
   * (table link, cart, name, pre-order). Only a thank-you with the invoice links stays, in memory.
   */
  endVisit(summary: EndedVisit): void {
    this._ended.set(summary);
    this.setTableToken(null);
    this.setGuestName('');
    this.setPreorder(null);
    this._lines.set([]);
    const slug = this.ctx.slug();
    if (slug) write(this.key(slug, 'cart'), null); // removed, not just emptied
  }

  /** A new visit starts (joined a table): the old thank-you goes away. */
  forgetEndedVisit(): void {
    this._ended.set(null);
  }

  setTableToken(token: string | null): void {
    if (token) this._ended.set(null);
    this._table.set(token);
    const slug = this.ctx.slug();
    if (slug) write(this.key(slug, 'table'), token);
  }

  setGuestName(name: string): void {
    const clean = name.trim().slice(0, 60);
    this._name.set(clean);
    const slug = this.ctx.slug();
    if (slug) write(this.key(slug, 'name'), clean || null);
  }

  setPreorder(reservationId: string | null): void {
    this._preorder.set(reservationId);
    const slug = this.ctx.slug();
    if (slug) write(this.key(slug, 'preorder'), reservationId);
  }

  /** Lines in the API shape. */
  toOrder(): OrderLineIn[] {
    return this._lines().map((l) => ({
      menu_item_id: l.menu_item_id,
      variant_id: l.variant_id,
      addon_ids: l.addon_ids,
      quantity: l.quantity,
      instructions: l.instructions,
    }));
  }

  private save(lines: CartLine[]): void {
    this._lines.set(lines);
    const slug = this.ctx.slug();
    if (slug) write(this.key(slug, 'cart'), lines);
  }

  private key(slug: string, what: string): string {
    return `wl.${what}.${slug}`;
  }
}

function round(n: number): number {
  return Math.round(n * 100) / 100;
}

export interface EndedVisit {
  code: string;
  restaurantName: string;
  /** invoice download links (they carry the old table link, which still works for reading) */
  receipts: { number: string; url: string }[];
}

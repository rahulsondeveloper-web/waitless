import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';

/** Inventory (PRD §8): raw materials, stock per branch, the movement ledger, suppliers, purchases, recipes. */

export type Unit = 'kg' | 'g' | 'l' | 'ml' | 'pcs' | 'pkt' | 'box';
export const UNITS: Unit[] = ['kg', 'g', 'l', 'ml', 'pcs', 'pkt', 'box'];
export const UNIT_LABEL: Record<Unit, string> = {
  kg: 'Kilogram (kg)',
  g: 'Gram (g)',
  l: 'Litre (l)',
  ml: 'Millilitre (ml)',
  pcs: 'Pieces',
  pkt: 'Packets',
  box: 'Boxes',
};
/** Units a recipe may use for an item stocked in `unit` (150 g of an item counted in kg). */
export function recipeUnits(unit: Unit): Unit[] {
  if (unit === 'kg' || unit === 'g') return ['g', 'kg'];
  if (unit === 'l' || unit === 'ml') return ['ml', 'l'];
  return [unit];
}

export type ManualType = 'opening' | 'addition' | 'wastage' | 'damage' | 'adjustment' | 'return';
export type MovementType =
  | ManualType
  | 'purchase'
  | 'consumption'
  | 'reversal'
  | 'transfer_out'
  | 'transfer_in';

export const MOVEMENT_LABEL: Record<MovementType, string> = {
  opening: 'Opening stock',
  purchase: 'Purchase',
  addition: 'Added',
  consumption: 'Used in orders',
  reversal: 'Order cancelled',
  wastage: 'Wastage',
  damage: 'Damaged',
  adjustment: 'Count correction',
  transfer_out: 'Transfer out',
  transfer_in: 'Transfer in',
  return: 'Returned to supplier',
};

export interface InventoryCategory {
  id: string;
  name: string;
  sort_order: number;
}

export interface InventoryItem {
  id: string;
  name: string;
  sku: string | null;
  category_id: string | null;
  category_name: string | null;
  supplier_id: string | null;
  supplier_name: string | null;
  unit: Unit;
  min_stock: string;
  reorder_level: string;
  purchase_price: string;
  tracks_expiry: boolean;
  storage_location: string;
  is_active: boolean;
}
export type InventoryItemInput = Omit<InventoryItem, 'id' | 'category_name' | 'supplier_name'>;

export interface StockRow {
  item_id: string;
  name: string;
  sku: string | null;
  unit: Unit;
  category_name: string | null;
  supplier_id: string | null;
  supplier_name: string | null;
  storage_location: string;
  on_hand: string;
  min_stock: string;
  reorder_level: string;
  avg_cost: string;
  value: string;
  state: 'ok' | 'low' | 'out';
  is_active: boolean;
  tracks_expiry: boolean;
}

export interface Movement {
  id: string;
  branch_id: string;
  item_id: string;
  item_name: string;
  unit: Unit;
  type: MovementType;
  quantity: string;
  balance_after: string;
  unit_cost: string | null;
  reason: string;
  actor_name: string | null;
  order_number: string | null;
  purchase_number: string | null;
  transfer_number: string | null;
  expiry_date: string | null;
  created_at: string;
}

export interface MovementInput {
  branch_id: string;
  item_id: string;
  type: ManualType;
  quantity: string;
  reason: string;
  unit_cost?: string | null;
  expiry_date?: string | null;
}

export interface Transfer {
  id: string;
  number: string;
  status: 'in_transit' | 'received' | 'cancelled';
  from_branch_id: string;
  from_branch_name: string;
  to_branch_id: string;
  to_branch_name: string;
  items: { item_id: string; name: string; unit: Unit; quantity: string }[];
  notes: string;
  created_at: string;
  received_at: string | null;
}

export interface Supplier {
  id: string;
  name: string;
  contact_name: string;
  phone: string;
  email: string;
  address: string;
  gstin: string;
  notes: string;
  is_active: boolean;
  purchases_count: number;
  purchases_total: string;
  outstanding: string;
}
export type SupplierInput = Omit<Supplier, 'id' | 'purchases_count' | 'purchases_total' | 'outstanding'>;

export interface PurchaseLine {
  item_id: string;
  name: string;
  unit: Unit;
  quantity: string;
  unit_price: string;
  tax_pct: string;
  line_total: string;
  tax_amount: string;
  received_quantity: string | null;
  expiry_date: string | null;
}

export interface Purchase {
  id: string;
  number: string;
  status: 'draft' | 'ordered' | 'received' | 'cancelled';
  branch_id: string;
  branch_name: string;
  supplier_id: string | null;
  supplier_name: string | null;
  order_date: string;
  expected_date: string | null;
  invoice_number: string;
  invoice_date: string | null;
  subtotal: string;
  tax_total: string;
  grand_total: string;
  amount_paid: string;
  payment_status: 'unpaid' | 'partial' | 'paid';
  notes: string;
  items: PurchaseLine[];
  payments: { id: string; amount: string; method: string; reference: string; paid_on: string }[];
  received_at: string | null;
  created_at: string;
}

export interface PurchaseInput {
  branch_id: string;
  supplier_id: string | null;
  order_date?: string | null;
  expected_date?: string | null;
  invoice_number: string;
  invoice_date?: string | null;
  notes: string;
  status: 'draft' | 'ordered';
  items: { item_id: string; quantity: string; unit_price: string; tax_pct: string }[];
}

export interface ReceiveInput {
  items: { item_id: string; received_quantity: string; expiry_date: string | null }[];
  invoice_number?: string | null;
  invoice_date?: string | null;
}

export interface RecipeLine {
  inventory_item_id: string;
  variant_id: string | null;
  quantity: string;
  unit: Unit;
  name?: string;
  stock_unit?: Unit;
  cost?: string;
}
export interface Recipe {
  menu_item_id: string;
  lines: RecipeLine[];
  cost: string;
}

export interface AlertRow {
  item_id: string;
  name: string;
  unit: Unit;
  on_hand: string;
  reorder_level: string;
  min_stock: string;
  state: 'low' | 'out';
  suggested_quantity: string;
  supplier_id: string | null;
  supplier_name: string | null;
  purchase_price: string;
}
export interface ExpiryRow {
  item_id: string;
  name: string;
  unit: Unit;
  quantity: string;
  expiry_date: string;
  days_left: number;
  on_hand: string;
}
export interface Alerts {
  low: AlertRow[];
  out: AlertRow[];
  expiring: ExpiryRow[];
}

export type ReportKind = 'current' | 'valuation' | 'movements' | 'consumption' | 'wastage' | 'purchases' | 'low_stock' | 'expiry';
export const REPORTS: { kind: ReportKind; label: string; dated: boolean }[] = [
  { kind: 'current', label: 'Current inventory', dated: false },
  { kind: 'valuation', label: 'Inventory valuation', dated: false },
  { kind: 'movements', label: 'Stock movement', dated: true },
  { kind: 'consumption', label: 'Consumption', dated: true },
  { kind: 'wastage', label: 'Wastage & damage', dated: true },
  { kind: 'purchases', label: 'Purchase history', dated: true },
  { kind: 'low_stock', label: 'Low stock', dated: false },
  { kind: 'expiry', label: 'Expiry', dated: false },
];
export interface Report {
  kind: ReportKind;
  title: string;
  columns: string[];
  rows: (string | number | null)[][];
  totals: Record<string, string>;
}

/** "4.5" instead of "4.500" — quantities are stored with three decimals. */
export function qty(v: string | number): string {
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? String(+n.toFixed(3)) : String(v);
}

/** RFC 4180 CSV (Excel-friendly: BOM, quoted fields). */
export function toCsv(columns: string[], rows: (string | number | null)[][]): string {
  const cell = (v: string | number | null) => {
    const s = v == null ? '' : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '﻿' + [columns, ...rows].map((r) => r.map(cell).join(',')).join('\r\n') + '\r\n';
}

export function downloadCsv(filename: string, csv: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

@Injectable({ providedIn: 'root' })
export class InventoryService {
  private readonly api = inject(ApiService);

  categories(): Observable<InventoryCategory[]> {
    return this.api.get('restaurant/inventory/categories');
  }
  createCategory(name: string): Observable<InventoryCategory> {
    return this.api.post('restaurant/inventory/categories', { name });
  }
  items(): Observable<InventoryItem[]> {
    return this.api.get('restaurant/inventory/items');
  }
  saveItem(data: InventoryItemInput, id?: string): Observable<InventoryItem> {
    return id ? this.api.put(`restaurant/inventory/items/${id}`, data) : this.api.post('restaurant/inventory/items', data);
  }
  stock(branchId: string, includeInactive = false): Observable<StockRow[]> {
    return this.api.get('restaurant/inventory/stock', { branch_id: branchId, include_inactive: includeInactive });
  }
  move(data: MovementInput): Observable<Movement> {
    return this.api.post('restaurant/inventory/movements', data);
  }
  movements(branchId: string, opts: { item_id?: string; limit?: number } = {}): Observable<Movement[]> {
    return this.api.get('restaurant/inventory/movements', { branch_id: branchId, ...opts });
  }
  alerts(branchId: string, days = 7): Observable<Alerts> {
    return this.api.get('restaurant/inventory/alerts', { branch_id: branchId, days });
  }
  report(kind: ReportKind, branchId: string, from?: string, to?: string): Observable<Report> {
    return this.api.get(`restaurant/inventory/reports/${kind}`, { branch_id: branchId, from, to });
  }
  transfers(branchId: string): Observable<Transfer[]> {
    return this.api.get('restaurant/inventory/transfers', { branch_id: branchId });
  }
  sendTransfer(data: {
    from_branch_id: string;
    to_branch_id: string;
    items: { item_id: string; quantity: string }[];
    notes: string;
  }): Observable<Transfer> {
    return this.api.post('restaurant/inventory/transfers', data);
  }
  finishTransfer(id: string, action: 'receive' | 'cancel'): Observable<Transfer> {
    return this.api.post(`restaurant/inventory/transfers/${id}/${action}`, {});
  }

  suppliers(): Observable<Supplier[]> {
    return this.api.get('restaurant/suppliers');
  }
  saveSupplier(data: SupplierInput, id?: string): Observable<Supplier> {
    return id ? this.api.put(`restaurant/suppliers/${id}`, data) : this.api.post('restaurant/suppliers', data);
  }

  purchases(opts: { branch_id?: string; supplier_id?: string } = {}): Observable<Purchase[]> {
    return this.api.get('restaurant/purchases', opts);
  }
  savePurchase(data: PurchaseInput, id?: string): Observable<Purchase> {
    return id ? this.api.put(`restaurant/purchases/${id}`, data) : this.api.post('restaurant/purchases', data);
  }
  purchaseAction(id: string, action: 'order' | 'cancel'): Observable<Purchase> {
    return this.api.post(`restaurant/purchases/${id}/${action}`, {});
  }
  receive(id: string, data: ReceiveInput): Observable<Purchase> {
    return this.api.post(`restaurant/purchases/${id}/receive`, data);
  }
  pay(id: string, data: { amount: string; method: string; reference: string; paid_on?: string | null }): Observable<Purchase> {
    return this.api.post(`restaurant/purchases/${id}/payments`, data);
  }

  recipe(menuItemId: string): Observable<Recipe> {
    return this.api.get(`restaurant/menu/items/${menuItemId}/recipe`);
  }
  saveRecipe(menuItemId: string, lines: RecipeLine[]): Observable<Recipe> {
    return this.api.put(`restaurant/menu/items/${menuItemId}/recipe`, {
      lines: lines.map(({ inventory_item_id, variant_id, quantity, unit }) => ({ inventory_item_id, variant_id, quantity, unit })),
    });
  }
}

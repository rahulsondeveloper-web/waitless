import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import { CheckoutData } from '../payments/checkout.service';
import { ChartSpec } from '../../shared/ui/chart/chart.component';

/** Restaurant reports (PRD §15) and the restaurant's own WaitLess plan / help requests. */

export interface ReportMeta {
  kind: string;
  title: string;
  feature: string;
}

export interface Report {
  kind: string;
  title: string;
  from: string;
  to: string;
  columns: string[];
  rows: (string | number | null)[][];
  totals: Record<string, string>;
  chart: ChartSpec;
}

/** Columns that hold rupee amounts (charts and totals are formatted as money). */
export const MONEY_REPORTS = new Set(['sales', 'payments', 'discounts', 'top_items']);

export interface Usage {
  plan: { code: string; name: string } | null;
  subscription: SubscriptionRow | null;
  limits: { key: string; label: string; used: number; limit: number | null }[];
  features: { key: string; label: string; enabled: boolean }[];
  last_30_days: { orders: number; sales: string; reservations: number };
}

export interface SubscriptionRow {
  id: string;
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  tenant_status: string;
  plan_id: string;
  plan_code: string;
  plan_name: string;
  status: 'trialing' | 'active' | 'past_due' | 'cancelled' | 'expired';
  billing_cycle: 'monthly' | 'yearly';
  trial_ends_at: string | null;
  current_period_start: string;
  current_period_end: string;
  grace_ends_at: string | null;
  auto_renew: boolean;
  cancelled_at: string | null;
  price: string;
  invoices_due: number;
  amount_due: string;
}

export interface SaasInvoice {
  id: string;
  number: string;
  tenant_id: string;
  tenant_name: string | null;
  description: string;
  period_start: string | null;
  period_end: string | null;
  amount: string;
  tax_pct: string;
  tax: string;
  total: string;
  currency: string;
  status: 'due' | 'paid' | 'void';
  due_date: string;
  paid_at: string | null;
  kind: 'renewal' | 'manual';
  created_at: string;
  payments: { id: string; amount: string; method: string; status: string; reference: string; created_at: string }[];
}

export interface Ticket {
  id: string;
  tenant_id: string | null;
  tenant_name: string | null;
  source: 'contact_form' | 'restaurant' | 'admin';
  topic: string;
  name: string;
  email: string;
  phone: string | null;
  message: string;
  status: 'open' | 'in_progress' | 'resolved' | 'closed';
  priority: 'low' | 'normal' | 'high' | 'urgent';
  assigned_to_id?: string | null;
  assigned_to_name: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  notes: { id: string; body: string; author: string | null; created_at: string }[] | null;
}

@Injectable({ providedIn: 'root' })
export class AnalyticsService {
  private readonly api = inject(ApiService);

  reports(): Observable<ReportMeta[]> {
    return this.api.get('restaurant/reports');
  }
  report(kind: string, opts: { branch_id?: string | null; from?: string; to?: string }): Observable<Report> {
    return this.api.get(`restaurant/reports/${kind}`, opts);
  }
  usage(): Observable<Usage> {
    return this.api.get('restaurant/subscription');
  }
  invoices(): Observable<SaasInvoice[]> {
    return this.api.get('restaurant/saas-invoices');
  }
  payInvoice(id: string): Observable<{ order_id: string; amount: string; checkout: CheckoutData }> {
    return this.api.post(`restaurant/saas-invoices/${id}/pay`, {});
  }
  mockPay(orderId: string, success: boolean): Observable<{ result: string }> {
    return this.api.post(`restaurant/saas-payments/mock/${encodeURIComponent(orderId)}`, { success });
  }
  limits(): Observable<{ manual_discount_pct: string; refund_amount: string }> {
    return this.api.get('restaurant/settings/limits');
  }
  saveLimits(v: { manual_discount_pct: string; refund_amount: string }): Observable<{ manual_discount_pct: string; refund_amount: string }> {
    return this.api.put('restaurant/settings/limits', v);
  }
  tickets(): Observable<Ticket[]> {
    return this.api.get('restaurant/support');
  }
  askHelp(topic: string, message: string): Observable<Ticket> {
    return this.api.post('restaurant/support', { topic, message });
  }
}

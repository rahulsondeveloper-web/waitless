import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { SaasInvoice, SubscriptionRow, Ticket, Usage } from '../analytics/analytics.service';
import { ApiService } from '../http/api.service';

/** WaitLess Super Admin (PRD §16–17): overview, plans, subscriptions, SaaS invoices, content, support, audit. */

export interface Overview {
  restaurants_total: number;
  restaurants_by_status: Record<'pending' | 'active' | 'suspended' | 'deactivated' | 'rejected', number>;
  branches: number;
  customers: number;
  orders: number;
  reservations: number;
  saas_revenue_total: string;
  saas_revenue_month: string;
  saas_outstanding: string;
  mrr: string;
  subscriptions_by_status: Record<'trialing' | 'active' | 'past_due', number>;
  subscriptions_expired_30d: number;
  subscriptions_by_plan: Record<string, number>;
  restaurant_sales_month: string;
  open_tickets: number;
}

export interface FeatureDef {
  key: string;
  label: string;
  kind: 'feature' | 'limit';
}

export interface PlanFeature {
  key: string;
  enabled: boolean;
  limit: number | null;
}

export interface Plan {
  id?: string;
  code: string;
  name: string;
  description: string | null;
  price_monthly: string;
  price_yearly: string;
  currency: string;
  trial_days: number;
  is_public: boolean;
  is_active: boolean;
  sort_order: number;
  features: PlanFeature[];
  subscribers?: number;
}

export type ContentMap = Record<string, Record<string, unknown>>;

export interface AuditEntry {
  id: string;
  created_at: string;
  action: string;
  entity: string;
  entity_id: string | null;
  tenant_id: string | null;
  tenant_name: string | null;
  actor_user_id: string | null;
  actor_name: string | null;
  actor_is_admin: boolean;
  diff: unknown;
  reason: string | null;
  ip: string | null;
}

export interface Template {
  event: string;
  label: string;
  channel: string;
  title: string;
  body: string;
  enabled: boolean;
  customised: boolean;
}

export interface PlatformSettings {
  settings: {
    grace_days: number;
    saas_tax_pct: string;
    invoice_due_days: number;
    support_email: string;
    support_phone: string;
    maintenance_banner: string;
    allow_registration: boolean;
  };
  integrations: { name: string; provider: string; status: string; note?: string }[];
}

@Injectable({ providedIn: 'root' })
export class SuperAdminService {
  private readonly api = inject(ApiService);
  private readonly base = 'super-admin';

  overview(): Observable<Overview> {
    return this.api.get(`${this.base}/overview`);
  }
  features(): Observable<FeatureDef[]> {
    return this.api.get(`${this.base}/features`);
  }
  plans(): Observable<Plan[]> {
    return this.api.get(`${this.base}/plans/full`);
  }
  savePlan(p: Plan): Observable<Plan> {
    const { id, subscribers: _s, ...body } = p;
    return id ? this.api.put(`${this.base}/plans/${id}`, body) : this.api.post(`${this.base}/plans`, body);
  }
  usage(tenantId: string): Observable<Usage> {
    return this.api.get(`${this.base}/restaurants/${tenantId}/usage`);
  }
  assign(tenantId: string, body: { plan_id: string; billing_cycle: string; trial: boolean; waive_first_invoice: boolean }): Observable<SubscriptionRow> {
    return this.api.post(`${this.base}/restaurants/${tenantId}/subscription`, body);
  }
  subscriptions(status?: string, q?: string): Observable<SubscriptionRow[]> {
    return this.api.get(`${this.base}/subscriptions`, { status, q });
  }
  subAction(id: string, action: string, days?: number): Observable<SubscriptionRow> {
    return this.api.post(`${this.base}/subscriptions/${id}/actions`, { action, days: days ?? null });
  }
  runRenewals(): Observable<Record<string, number>> {
    return this.api.post(`${this.base}/subscriptions/run-renewals`, {});
  }
  invoices(opts: { tenant_id?: string; status?: string } = {}): Observable<SaasInvoice[]> {
    return this.api.get(`${this.base}/saas-invoices`, opts);
  }
  createInvoice(tenantId: string, amount: string, description: string): Observable<SaasInvoice> {
    return this.api.post(`${this.base}/saas-invoices`, { tenant_id: tenantId, amount, description });
  }
  recordPayment(id: string, method: string, reference: string): Observable<SaasInvoice> {
    return this.api.post(`${this.base}/saas-invoices/${id}/payments`, { method, reference });
  }
  voidInvoice(id: string, reason: string): Observable<SaasInvoice> {
    return this.api.post(`${this.base}/saas-invoices/${id}/void`, { reason });
  }
  content(): Observable<ContentMap> {
    return this.api.get(`${this.base}/content`);
  }
  saveContent(key: string, data: Record<string, unknown>): Observable<Record<string, unknown>> {
    return this.api.put(`${this.base}/content/${key}`, data);
  }
  tickets(status?: string, q?: string): Observable<Ticket[]> {
    return this.api.get(`${this.base}/support/tickets`, { status, q });
  }
  ticket(id: string): Observable<Ticket> {
    return this.api.get(`${this.base}/support/tickets/${id}`);
  }
  updateTicket(id: string, body: Partial<{ status: string; priority: string; assigned_to_id: string | null }>): Observable<Ticket> {
    return this.api.patch(`${this.base}/support/tickets/${id}`, body);
  }
  addNote(id: string, body: string): Observable<Ticket> {
    return this.api.post(`${this.base}/support/tickets/${id}/notes`, { body });
  }
  admins(): Observable<{ id: string; name: string; email: string }[]> {
    return this.api.get(`${this.base}/admins`);
  }
  audit(params: Record<string, string | number | boolean | undefined | null>): Observable<{ items: AuditEntry[]; total: number; page: number; page_size: number }> {
    return this.api.get(`${this.base}/audit`, params);
  }
  settings(): Observable<PlatformSettings> {
    return this.api.get(`${this.base}/settings`);
  }
  saveSettings(s: PlatformSettings['settings']): Observable<PlatformSettings> {
    return this.api.put(`${this.base}/settings`, s);
  }
  templates(): Observable<Template[]> {
    return this.api.get(`${this.base}/notification-templates`);
  }
  saveTemplate(t: Template): Observable<Template[]> {
    return this.api.put(`${this.base}/notification-templates/${t.event}`, { title: t.title, body: t.body, enabled: t.enabled });
  }
}

/** Mirrors backend app/schemas/auth.py. */

export interface UserInfo {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  is_super_admin: boolean;
}

export interface Feature {
  enabled: boolean;
  limit: number | null;
}

export interface SubscriptionInfo {
  plan_code: string;
  plan_name: string;
  status: 'trialing' | 'active' | 'past_due' | 'cancelled' | 'expired';
  trial_ends_at: string | null;
  current_period_end: string;
}

export type TenantStatus = 'pending' | 'active' | 'suspended' | 'deactivated' | 'rejected';

export interface Membership {
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  tenant_status: TenantStatus;
  role_key: string;
  role_name: string;
}

export interface ActiveTenant extends Membership {
  permissions: Record<string, 'all' | 'own_branches'>;
  all_branches: boolean;
  branch_ids: string[];
  features: Record<string, Feature>;
  subscription: SubscriptionInfo | null;
}

export interface Me {
  user: UserInfo;
  memberships: Membership[];
  active_tenant: ActiveTenant | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  me: Me;
}

export interface OtpSendResponse {
  phone: string;
  expires_in_seconds: number;
  dev_code: string | null;
}

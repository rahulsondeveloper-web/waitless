import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from '../http/api.service';
import { Branch } from '../tenancy/tenancy.models';

/** Mirrors backend app/schemas/staff.py and app/schemas/tables.py. */

export type Scope = 'all' | 'own_branches';
export type TableStatus = 'available' | 'reserved' | 'occupied' | 'cleaning';

export interface BranchCreate {
  name: string;
  address_line: string;
  city: string;
  state: string;
  country: string;
  postal_code?: string | null;
  phone?: string | null;
  timezone?: string;
}

export interface Staff {
  membership_id: string;
  user_id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
  role_id: string;
  role_key: string;
  role_name: string;
  status: 'active' | 'invited' | 'disabled';
  all_branches: boolean;
  branch_ids: string[];
  last_login_at: string | null;
  is_owner: boolean;
  is_you: boolean;
}

export interface StaffInvite {
  full_name: string;
  phone: string;
  email?: string | null;
  role_id: string;
  all_branches: boolean;
  branch_ids: string[];
}

export interface Role {
  id: string;
  key: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: Record<string, Scope>;
  member_count: number;
}

export interface Permission {
  key: string;
  module: string;
  description: string;
}

export interface Section {
  id: string;
  branch_id: string;
  name: string;
  sort_order: number;
}

export interface Table {
  id: string;
  branch_id: string;
  section_id: string | null;
  label: string;
  capacity: number;
  status: TableStatus;
  is_active: boolean;
  sort_order: number;
}

export interface BoardTable extends Table {
  section_name: string | null;
  session: {
    id: string;
    public_code: string;
    party_size: number;
    guest_name: string | null;
    opened_at: string;
    source: string;
  } | null;
}

export interface Board {
  branch_id: string;
  tables: BoardTable[];
  sections: Section[];
  counts: Record<TableStatus, number>;
  server_time: string;
}

export interface TableSession {
  id: string;
  branch_id: string;
  public_code: string;
  status: string;
  party_size: number;
  guest_name: string | null;
  table_ids: string[];
  opened_at: string;
  closed_at: string | null;
}

export interface Seated {
  session: TableSession;
  pin: string;
}

export interface Dashboard {
  branch_id: string | null;
  tables_total: number;
  tables_by_status: Record<TableStatus, number>;
  open_sessions: number;
  guests_seated: number;
  branches_active: number;
  staff_active: number;
  dishes_live: number;
  todays_revenue: string | null;
  orders_today: number | null;
  active_orders: number | null;
  active_reservations: number | null;
  queue_length: number | null;
  average_wait_minutes: number | null;
  average_serving_minutes: number | null;
  delayed_orders: number | null;
  discounts_today: string | null;
  low_inventory_alerts: number | null;
}

export const STATUS_LABEL: Record<TableStatus, string> = {
  available: 'Available',
  reserved: 'Reserved',
  occupied: 'Occupied',
  cleaning: 'Cleaning',
};

@Injectable({ providedIn: 'root' })
export class OperationsService {
  private readonly api = inject(ApiService);

  dashboard(branchId?: string | null): Observable<Dashboard> {
    return this.api.get('restaurant/dashboard', { branch_id: branchId });
  }

  // Branches
  branches(): Observable<Branch[]> {
    return this.api.get('restaurant/branches');
  }
  createBranch(body: BranchCreate): Observable<Branch> {
    return this.api.post('restaurant/branches', body);
  }
  setBranchActive(id: string, active: boolean): Observable<Branch> {
    return this.api.patch(`restaurant/branches/${id}/status`, { is_active: active });
  }

  // Staff & roles
  staff(): Observable<Staff[]> {
    return this.api.get('restaurant/staff');
  }
  invite(body: StaffInvite): Observable<Staff> {
    return this.api.post('restaurant/staff', body);
  }
  updateStaff(id: string, body: Partial<Pick<Staff, 'role_id' | 'all_branches' | 'branch_ids' | 'status'>>): Observable<Staff> {
    return this.api.patch(`restaurant/staff/${id}`, body);
  }
  removeStaff(id: string): Observable<void> {
    return this.api.delete(`restaurant/staff/${id}`);
  }
  roles(): Observable<Role[]> {
    return this.api.get('restaurant/roles');
  }
  permissions(): Observable<Permission[]> {
    return this.api.get('restaurant/permissions');
  }
  createRole(body: { name: string; description?: string | null; permissions: Record<string, Scope> }): Observable<Role> {
    return this.api.post('restaurant/roles', body);
  }
  updateRole(id: string, body: { name?: string; description?: string | null; permissions?: Record<string, Scope> }): Observable<Role> {
    return this.api.patch(`restaurant/roles/${id}`, body);
  }
  deleteRole(id: string): Observable<void> {
    return this.api.delete(`restaurant/roles/${id}`);
  }

  // Sections & tables
  sections(branchId: string): Observable<Section[]> {
    return this.api.get('restaurant/sections', { branch_id: branchId });
  }
  createSection(branchId: string, name: string): Observable<Section> {
    return this.api.post('restaurant/sections', { branch_id: branchId, name });
  }
  renameSection(id: string, name: string): Observable<Section> {
    return this.api.patch(`restaurant/sections/${id}`, { name });
  }
  deleteSection(id: string): Observable<void> {
    return this.api.delete(`restaurant/sections/${id}`);
  }
  tables(branchId: string): Observable<Table[]> {
    return this.api.get('restaurant/tables', { branch_id: branchId });
  }
  createTable(body: { branch_id: string; section_id: string | null; label: string; capacity: number }): Observable<Table> {
    return this.api.post('restaurant/tables', body);
  }
  updateTable(id: string, body: Partial<Pick<Table, 'section_id' | 'label' | 'capacity' | 'is_active'>>): Observable<Table> {
    return this.api.patch(`restaurant/tables/${id}`, body);
  }
  board(branchId: string): Observable<Board> {
    return this.api.get('restaurant/tables/board', { branch_id: branchId });
  }
  setTableStatus(id: string, status: Exclude<TableStatus, 'occupied'>): Observable<Table> {
    return this.api.patch(`restaurant/tables/${id}/status`, { status });
  }

  // Sessions
  seat(tableId: string, partySize: number, guestName?: string | null): Observable<Seated> {
    return this.api.post('restaurant/table-sessions', { table_id: tableId, party_size: partySize, guest_name: guestName || null });
  }
  transfer(sessionId: string, tableId: string): Observable<TableSession> {
    return this.api.post(`restaurant/table-sessions/${sessionId}/transfer`, { table_id: tableId });
  }
  closeSession(sessionId: string): Observable<TableSession> {
    return this.api.post(`restaurant/table-sessions/${sessionId}/close`, {});
  }
  newPin(sessionId: string): Observable<Seated> {
    return this.api.post(`restaurant/table-sessions/${sessionId}/pin`, {});
  }
}

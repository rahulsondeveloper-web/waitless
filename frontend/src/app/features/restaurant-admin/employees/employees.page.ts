import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { Observable, filter, forkJoin } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { OperationsService, Permission, Role, Staff } from '../../../core/restaurant/operations.service';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ConfirmData, ConfirmDialogComponent } from '../../../shared/ui/confirm-dialog/confirm-dialog.component';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { RoleDialogComponent, RoleDialogData } from './role-dialog.component';
import { StaffDialogComponent, StaffDialogData } from './staff-dialog.component';

/** Employees and roles (PRD §3.2, §15). */
@Component({
  selector: 'wl-employees-page',
  imports: [DatePipe, MatTabsModule, MatButtonModule, MatIconModule, MatMenuModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './employees.page.html',
  styleUrl: './employees.page.scss',
})
export class EmployeesPage implements OnInit {
  private readonly ops = inject(OperationsService);
  private readonly tenancy = inject(TenancyService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly auth = inject(AuthService);

  protected readonly staff = signal<Staff[] | null>(null);
  protected readonly roles = signal<Role[]>([]);
  protected readonly branches = signal<Branch[]>([]);
  protected readonly permissions = signal<Permission[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly fullAdmin = computed(() => this.auth.activeTenant()?.permissions['staff.manage'] === 'all');
  protected readonly branchName = computed(() => new Map(this.branches().map((b) => [b.id, b.name])));

  ngOnInit(): void {
    forkJoin({
      staff: this.ops.staff(),
      roles: this.ops.roles(),
      me: this.tenancy.restaurantMe(),
      permissions: this.ops.permissions(),
    }).subscribe({
      next: ({ staff, roles, me, permissions }) => {
        this.staff.set(staff);
        this.roles.set(roles);
        this.branches.set(me.branches.filter((b) => b.is_active));
        this.permissions.set(permissions);
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected branchesOf(s: Staff): string {
    if (s.all_branches) return 'All branches';
    return s.branch_ids.map((id) => this.branchName().get(id) ?? '—').join(', ') || '—';
  }

  protected openStaff(staff: Staff | null): void {
    const data: StaffDialogData = {
      staff,
      roles: this.roles(),
      branches: this.branches(),
      fullAdmin: this.fullAdmin(),
      myBranchIds: this.auth.activeTenant()?.branch_ids ?? [],
    };
    this.dialog
      .open<StaffDialogComponent, StaffDialogData, Staff>(StaffDialogComponent, { data, maxWidth: '96vw' })
      .afterClosed()
      .pipe(filter((s): s is Staff => !!s))
      .subscribe((saved) => {
        this.staff.update((list) => {
          const rest = (list ?? []).filter((x) => x.membership_id !== saved.membership_id);
          return [...rest, saved];
        });
        this.refreshRoles();
        this.snack.open(staff ? 'Employee updated.' : `${saved.full_name} added. They sign in with their mobile number.`, undefined, {
          duration: 4000,
        });
      });
  }

  protected setStatus(s: Staff, status: 'active' | 'disabled'): void {
    this.run(this.ops.updateStaff(s.membership_id, { status }), (saved) =>
      this.staff.update((list) => (list ?? []).map((x) => (x.membership_id === saved.membership_id ? saved : x))),
    );
  }

  protected remove(s: Staff): void {
    const data: ConfirmData = {
      title: `Remove ${s.full_name}?`,
      message: 'They lose access to this restaurant immediately. Their WaitLess account stays.',
      confirm: 'Remove',
      danger: true,
    };
    this.confirm(data, () =>
      this.run(this.ops.removeStaff(s.membership_id), () => {
        this.staff.update((list) => (list ?? []).filter((x) => x.membership_id !== s.membership_id));
        this.refreshRoles();
      }),
    );
  }

  protected openRole(role: Role | null): void {
    this.dialog
      .open<RoleDialogComponent, RoleDialogData, Role>(RoleDialogComponent, {
        data: { role, permissions: this.permissions() },
        width: '620px',
        maxWidth: '96vw',
      })
      .afterClosed()
      .pipe(filter((r): r is Role => !!r))
      .subscribe(() => this.refreshRoles());
  }

  protected deleteRole(role: Role): void {
    this.confirm({ title: `Delete role "${role.name}"?`, message: 'This cannot be undone.', confirm: 'Delete', danger: true }, () =>
      this.run(this.ops.deleteRole(role.id), () => this.refreshRoles()),
    );
  }

  protected permCount(r: Role): number {
    return Object.keys(r.permissions).length;
  }

  private refreshRoles(): void {
    this.ops.roles().subscribe((r) => this.roles.set(r));
  }

  private confirm(data: ConfirmData, then: () => void): void {
    this.dialog.open(ConfirmDialogComponent, { data, width: '420px' }).afterClosed().pipe(filter(Boolean)).subscribe(then);
  }

  private run<T>(obs: Observable<T>, done: (v: T) => void): void {
    obs.subscribe({ next: done, error: (e: ApiError) => this.snack.open(e.message, 'Dismiss', { duration: 5000 }) });
  }
}

import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { Observable, filter, interval } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import {
  Board,
  BoardTable,
  OperationsService,
  STATUS_LABEL,
  Section,
  Table,
  TableStatus,
} from '../../../core/restaurant/operations.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ConfirmData, ConfirmDialogComponent } from '../../../shared/ui/confirm-dialog/confirm-dialog.component';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import {
  CodeDialogComponent,
  SeatDialogComponent,
  SeatDialogData,
  SeatDialogResult,
  TransferDialogComponent,
  TransferDialogData,
} from './table-dialogs';

/**
 * Table management (PRD §11): live floor board (green available, yellow reserved, red occupied,
 * blue cleaning) and setup of sections/tables. Live via Socket.IO room of the branch.
 */
@Component({
  selector: 'wl-tables-page',
  imports: [
    MatTabsModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatSlideToggleModule,
    LoadingStateComponent,
    ErrorStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './tables.page.html',
  styleUrl: './tables.page.scss',
})
export class TablesPage implements OnInit {
  private readonly ops = inject(OperationsService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly auth = inject(AuthService);

  protected readonly statusLabel = STATUS_LABEL;
  protected readonly statuses: TableStatus[] = ['available', 'reserved', 'occupied', 'cleaning'];
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly board = signal<Board | null>(null);
  protected readonly setupTables = signal<Table[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly live = signal(false);
  protected readonly now = signal(Date.now());
  protected readonly canConfigure = computed(() => this.auth.hasPermission('tables.configure'));

  /** Tables grouped by section for the floor view. */
  protected readonly groups = computed(() => {
    const b = this.board();
    if (!b) return [];
    const groups: { name: string; tables: BoardTable[] }[] = b.sections.map((s) => ({
      name: s.name,
      tables: b.tables.filter((t) => t.section_id === s.id),
    }));
    const loose = b.tables.filter((t) => !t.section_id);
    if (loose.length) groups.push({ name: b.sections.length ? 'Other tables' : 'Tables', tables: loose });
    return groups.filter((g) => g.tables.length);
  });

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        const first = active.find((b) => b.is_primary) ?? active[0];
        if (first) this.selectBranch(first.id);
        else this.board.set({ branch_id: '', tables: [], sections: [], counts: { available: 0, reserved: 0, occupied: 0, cleaning: 0 }, server_time: '' });
      },
      error: (e: ApiError) => this.error.set(e),
    });
    const off = this.realtime.on<{ branch_id: string }>('tables.changed', (e) => {
      if (e.branch_id === this.branchId()) this.reload();
    });
    interval(30_000).pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.now.set(Date.now()));
    this.destroyRef.onDestroy(() => {
      off();
      const b = this.branchId();
      if (b) this.realtime.unsubscribeBranch(b);
    });
  }

  protected selectBranch(id: string): void {
    const previous = this.branchId();
    if (previous && previous !== id) this.realtime.unsubscribeBranch(previous);
    this.branchId.set(id);
    this.board.set(null);
    this.reload();
    void this.realtime.subscribeBranch(id).then((ok) => this.live.set(ok));
  }

  protected reload(): void {
    const id = this.branchId();
    if (!id) return;
    this.ops.board(id).subscribe({ next: (b) => this.board.set(b), error: (e: ApiError) => this.error.set(e) });
    if (this.canConfigure()) this.ops.tables(id).subscribe((t) => this.setupTables.set(t));
  }

  protected minutesSince(iso: string): number {
    return Math.max(0, Math.floor((this.now() - Date.parse(iso)) / 60_000));
  }

  // ---------- floor actions ----------

  protected seat(table: BoardTable): void {
    this.dialog
      .open<SeatDialogComponent, SeatDialogData, SeatDialogResult>(SeatDialogComponent, { data: { table } })
      .afterClosed()
      .pipe(filter((r): r is SeatDialogResult => !!r))
      .subscribe((r) =>
        this.run(table.id, this.ops.seat(table.id, r.partySize, r.guestName), (seated) => {
          this.reload();
          this.dialog.open(CodeDialogComponent, { data: seated, width: '420px' });
        }),
      );
  }

  protected setStatus(table: BoardTable, status: 'available' | 'reserved' | 'cleaning'): void {
    this.run(table.id, this.ops.setTableStatus(table.id, status), () => this.reload());
  }

  protected move(table: BoardTable): void {
    const b = this.board();
    if (!b || !table.session) return;
    const free = b.tables.filter((t) => t.id !== table.id && (t.status === 'available' || t.status === 'reserved'));
    this.dialog
      .open<TransferDialogComponent, TransferDialogData, string>(TransferDialogComponent, { data: { from: table, free } })
      .afterClosed()
      .pipe(filter((id): id is string => !!id))
      .subscribe((to) =>
        this.run(table.id, this.ops.transfer(table.session!.id, to), () => {
          this.reload();
          this.snack.open('Guests moved.', undefined, { duration: 2000 });
        }),
      );
  }

  protected newPin(table: BoardTable): void {
    if (!table.session) return;
    this.run(table.id, this.ops.newPin(table.session.id), (seated) =>
      this.dialog.open(CodeDialogComponent, { data: seated, width: '420px' }),
    );
  }

  protected guestsLeft(table: BoardTable): void {
    if (!table.session) return;
    const data: ConfirmData = {
      title: `Guests left ${table.label}?`,
      message: 'The table session is closed and the table goes to cleaning.',
      confirm: 'Close table',
    };
    this.confirm(data, () => this.run(table.id, this.ops.closeSession(table.session!.id), () => this.reload()));
  }

  // ---------- setup ----------

  protected addSection(input: HTMLInputElement): void {
    const id = this.branchId();
    const name = input.value.trim();
    if (!id || !name) return;
    this.run('section', this.ops.createSection(id, name), () => {
      input.value = '';
      this.reload();
    });
  }

  protected renameSection(s: Section, name: string): void {
    const clean = name.trim();
    if (!clean || clean === s.name) return;
    this.run(s.id, this.ops.renameSection(s.id, clean), () => this.reload());
  }

  protected deleteSection(s: Section): void {
    this.confirm(
      { title: `Delete section "${s.name}"?`, message: 'Its tables stay, without a section.', confirm: 'Delete', danger: true },
      () => this.run(s.id, this.ops.deleteSection(s.id), () => this.reload()),
    );
  }

  protected addTable(label: HTMLInputElement, capacity: HTMLInputElement, section: HTMLSelectElement): void {
    const id = this.branchId();
    const cap = Number(capacity.value);
    if (!id || !label.value.trim() || !(cap >= 1 && cap <= 50)) {
      this.snack.open('Enter a table name and 1–50 seats.', 'OK', { duration: 3000 });
      return;
    }
    this.run(
      'table',
      this.ops.createTable({ branch_id: id, label: label.value.trim(), capacity: cap, section_id: section.value || null }),
      () => {
        label.value = '';
        this.reload();
      },
    );
  }

  protected updateTable(t: Table, change: Partial<Pick<Table, 'section_id' | 'label' | 'capacity' | 'is_active'>>): void {
    this.run(t.id, this.ops.updateTable(t.id, change), () => this.reload());
  }

  // ---------- helpers ----------

  private confirm(data: ConfirmData, then: () => void): void {
    this.dialog.open(ConfirmDialogComponent, { data, width: '400px' }).afterClosed().pipe(filter(Boolean)).subscribe(then);
  }

  private run<T>(key: string, obs: Observable<T>, done: (v: T) => void): void {
    this.busy.set(key);
    obs.subscribe({
      next: (v) => {
        this.busy.set(null);
        done(v);
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        this.snack.open(e.message, 'Dismiss', { duration: 5000 });
        this.reload();
      },
    });
  }
}

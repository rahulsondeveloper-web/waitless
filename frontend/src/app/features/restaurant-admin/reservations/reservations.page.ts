import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { Observable, filter } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import {
  Availability,
  BookingPolicy,
  BookingsService,
  RESERVATION_STATUS_LABEL,
  Reservation,
  formatWhen,
  localDate,
} from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { BoardTable, OperationsService } from '../../../core/restaurant/operations.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ConfirmData, ConfirmDialogComponent } from '../../../shared/ui/confirm-dialog/confirm-dialog.component';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { CodeDialogComponent } from '../tables/table-dialogs';

type PolicyForm = Omit<BookingPolicy, 'branch_id'>;

/** Reservations (PRD §12): day list, confirm arrival, phone bookings, no-show/cancel and the booking policy. */
@Component({
  selector: 'wl-reservations-page',
  imports: [
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatSlideToggleModule,
    MatTabsModule,
    LoadingStateComponent,
    ErrorStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './reservations.page.html',
  styleUrls: ['../admin-bookings.scss', './reservations.page.scss'],
})
export class ReservationsAdminPage implements OnInit {
  private readonly api = inject(BookingsService);
  private readonly ops = inject(OperationsService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly auth = inject(AuthService);

  protected readonly statusLabel = RESERVATION_STATUS_LABEL;
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly date = signal('');
  protected readonly list = signal<Reservation[] | null>(null);
  protected readonly tables = signal<BoardTable[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly live = signal(false);
  protected readonly policy = signal<PolicyForm | null>(null);
  protected readonly slots = signal<Availability | null>(null);
  protected phone = { name: '', phone: '', party: 2, date: '', slot: '', notes: '' };

  protected readonly tz = computed(() => this.branches().find((b) => b.id === this.branchId())?.timezone ?? 'Asia/Kolkata');
  protected readonly canManage = computed(() => this.auth.hasPermission('reservations.manage'));
  protected readonly canEditPolicy = computed(() => this.auth.hasPermission('reservations.policy.manage'));
  protected readonly paidAllowed = computed(() => this.auth.hasFeature('reservations.paid'));
  protected readonly counts = computed(() => {
    const l = this.list() ?? [];
    return {
      total: l.length,
      guests: l.filter((r) => ['confirmed', 'checked_in', 'completed'].includes(r.status)).reduce((s, r) => s + r.party_size, 0),
      waiting: l.filter((r) => r.status === 'confirmed').length,
      arrived: l.filter((r) => r.status === 'checked_in' || r.status === 'completed').length,
    };
  });

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        const first = active.find((b) => b.is_primary) ?? active[0];
        if (first) this.selectBranch(first.id);
        else this.list.set([]);
      },
      error: (e: ApiError) => this.error.set(e),
    });
    const off = this.realtime.on<{ branch_id: string }>('reservations.changed', (e) => {
      if (e.branch_id === this.branchId()) this.reload();
    });
    this.destroyRef.onDestroy(() => {
      off();
      const b = this.branchId();
      if (b) this.realtime.unsubscribeBranch(b);
    });
  }

  protected when(iso: string): string {
    return formatWhen(iso, this.tz());
  }

  protected time(iso: string): string {
    return new Intl.DateTimeFormat('en-IN', { timeZone: this.tz(), hour: '2-digit', minute: '2-digit', hour12: false }).format(
      new Date(iso),
    );
  }

  protected selectBranch(id: string): void {
    const previous = this.branchId();
    if (previous && previous !== id) this.realtime.unsubscribeBranch(previous);
    this.branchId.set(id);
    if (!this.date()) this.date.set(localDate(this.tz()));
    this.phone.date = this.date();
    this.list.set(null);
    this.reload();
    this.loadPolicy();
    this.loadSlots();
    void this.realtime.subscribeBranch(id).then((ok) => this.live.set(ok));
  }

  protected setDate(d: string): void {
    this.date.set(d);
    this.reload();
  }

  protected shiftDay(days: number): void {
    const d = new Date(`${this.date()}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + days);
    this.setDate(d.toISOString().slice(0, 10));
  }

  protected reload(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.reservations(id, this.date()).subscribe({ next: (l) => this.list.set(l), error: (e: ApiError) => this.error.set(e) });
    this.ops.board(id).subscribe({ next: (b) => this.tables.set(b.tables), error: () => undefined });
  }

  /** Tables to seat a booking at: the held one first, then other free tables that fit. */
  protected seatOptions(r: Reservation): BoardTable[] {
    return this.tables()
      .filter((t) => t.capacity >= r.party_size && (t.status === 'available' || t.status === 'reserved'))
      .sort((a, b) => Number(r.table_labels.includes(b.label)) - Number(r.table_labels.includes(a.label)));
  }

  protected arrive(r: Reservation, tableId: string | null): void {
    this.run(r.id, this.api.arrive(r.id, tableId), (seated) => {
      this.reload();
      this.dialog.open(CodeDialogComponent, { data: seated, width: '420px' });
    });
  }

  protected noShow(r: Reservation): void {
    this.confirm(
      { title: `Mark ${r.guest_name} as no-show?`, message: 'The table is released.', confirm: 'No-show', danger: true },
      () => this.run(r.id, this.api.noShow(r.id), () => this.reload()),
    );
  }

  protected cancel(r: Reservation): void {
    const fee = r.type === 'paid' && r.payment_status === 'captured' ? ` The ₹${r.booking_fee} fee is refunded in full.` : '';
    this.confirm(
      { title: `Cancel booking ${r.code}?`, message: `The guest is notified.${fee}`, confirm: 'Cancel booking', danger: true },
      () => this.run(r.id, this.api.staffCancel(r.id), () => this.reload()),
    );
  }

  // ---------- phone booking ----------

  protected loadSlots(): void {
    const id = this.branchId();
    if (!id || !this.phone.date) return;
    this.phone.slot = '';
    this.api.staffAvailability(id, this.phone.date, Math.max(1, this.phone.party)).subscribe({
      next: (a) => this.slots.set(a),
      error: () => this.slots.set(null),
    });
  }

  protected addPhoneBooking(): void {
    const id = this.branchId();
    if (!id || !this.phone.name.trim() || !this.phone.slot) {
      this.snack.open('Enter the guest name and pick a time.', 'OK', { duration: 3000 });
      return;
    }
    this.run(
      'phone',
      this.api.staffBook({
        branch_id: id,
        starts_at: this.phone.slot,
        party_size: this.phone.party,
        guest_name: this.phone.name.trim(),
        phone: this.phone.phone.trim() || null,
        notes: this.phone.notes.trim(),
      }),
      (res) => {
        this.snack.open(`Booked ${res.reservation.code} · table ${res.reservation.table_labels.join(', ')}`, undefined, {
          duration: 3000,
        });
        this.phone = { ...this.phone, name: '', phone: '', notes: '', slot: '' };
        this.setDate(this.phone.date);
        this.loadSlots();
      },
    );
  }

  // ---------- policy ----------

  protected loadPolicy(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.policy(id).subscribe({
      next: ({ branch_id: _b, ...p }) => this.policy.set(p),
      error: () => this.policy.set(null),
    });
  }

  protected savePolicy(): void {
    const id = this.branchId();
    const p = this.policy();
    if (!id || !p) return;
    this.run('policy', this.api.savePolicy(id, { ...p, booking_fee: String(p.booking_fee || 0) }), ({ branch_id: _b, ...saved }) => {
      this.policy.set(saved);
      this.snack.open('Booking policy saved.', undefined, { duration: 2000 });
      this.loadSlots();
    });
  }

  protected patchPolicy<K extends keyof PolicyForm>(key: K, value: PolicyForm[K]): void {
    const p = this.policy();
    if (p) this.policy.set({ ...p, [key]: value });
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

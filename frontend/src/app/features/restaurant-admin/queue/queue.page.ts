import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTooltipModule } from '@angular/material/tooltip';
import QRCode from 'qrcode';
import { Observable, interval } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { BookingsService, QUEUE_STATUS_LABEL, QueueEntry } from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { BoardTable, OperationsService } from '../../../core/restaurant/operations.service';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { CodeDialogComponent } from '../tables/table-dialogs';

/** Walk-in queue (PRD §12): add guests, "table ready" notifications, seat, reorder, skip/no-show. Live. */
@Component({
  selector: 'wl-queue-page',
  imports: [
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatTabsModule,
    MatTooltipModule,
    LoadingStateComponent,
    ErrorStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './queue.page.html',
  styleUrls: ['../admin-bookings.scss', './queue.page.scss'],
})
export class QueuePage implements OnInit {
  private readonly api = inject(BookingsService);
  private readonly ops = inject(OperationsService);
  private readonly tenancy = inject(TenancyService);
  private readonly realtime = inject(RealtimeService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(AuthService);

  protected readonly statusLabel = QUEUE_STATUS_LABEL;
  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly entries = signal<QueueEntry[] | null>(null);
  protected readonly history = signal<QueueEntry[]>([]);
  protected readonly tables = signal<BoardTable[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly live = signal(false);
  protected readonly now = signal(Date.now());
  protected readonly qr = signal<string | null>(null);
  protected guest = { name: '', party: 2, phone: '' };

  protected readonly queueUrl = computed(() => {
    const slug = this.auth.activeTenant()?.tenant_slug;
    return slug ? `${location.origin}/r/${slug}/queue` : '';
  });
  protected readonly freeTables = computed(() => this.tables().filter((t) => t.status === 'available'));

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        const first = active.find((b) => b.is_primary) ?? active[0];
        if (first) this.selectBranch(first.id);
        else this.entries.set([]);
      },
      error: (e: ApiError) => this.error.set(e),
    });
    const offQ = this.realtime.on<{ branch_id: string }>('queue.changed', (e) => {
      if (e.branch_id === this.branchId()) this.reload();
    });
    const offT = this.realtime.on<{ branch_id: string }>('tables.changed', (e) => {
      if (e.branch_id === this.branchId()) this.loadTables();
    });
    interval(30_000)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.now.set(Date.now()));
    this.destroyRef.onDestroy(() => {
      offQ();
      offT();
      const b = this.branchId();
      if (b) this.realtime.unsubscribeBranch(b);
    });
    const url = this.queueUrl();
    if (url) void QRCode.toDataURL(url, { margin: 1, width: 360 }).then((d) => this.qr.set(d));
  }

  protected selectBranch(id: string): void {
    const previous = this.branchId();
    if (previous && previous !== id) this.realtime.unsubscribeBranch(previous);
    this.branchId.set(id);
    this.entries.set(null);
    this.reload();
    void this.realtime.subscribeBranch(id).then((ok) => this.live.set(ok));
  }

  protected reload(): void {
    const id = this.branchId();
    if (!id) return;
    this.api.queue(id).subscribe({ next: (e) => this.entries.set(e), error: (e: ApiError) => this.error.set(e) });
    this.api.queue(id, true).subscribe({ next: (e) => this.history.set(e), error: () => undefined });
    this.loadTables();
  }

  protected waited(e: QueueEntry): number {
    return Math.max(0, Math.floor((this.now() - Date.parse(e.joined_at)) / 60_000));
  }

  /** Tables big enough for the party: free ones, plus the one held for this guest. */
  protected tablesFor(e: QueueEntry): BoardTable[] {
    return this.tables().filter(
      (t) =>
        t.capacity >= e.party_size &&
        (t.status === 'available' || (t.status === 'reserved' && t.label === e.notified_table_label)),
    );
  }

  protected add(): void {
    const id = this.branchId();
    const name = this.guest.name.trim();
    if (!id || !name || !(this.guest.party >= 1)) {
      this.snack.open('Enter the guest name and party size.', 'OK', { duration: 3000 });
      return;
    }
    this.run(
      'add',
      this.api.addToQueue({ branch_id: id, guest_name: name, party_size: this.guest.party, phone: this.guest.phone.trim() || null }),
      (e) => {
        this.guest = { name: '', party: 2, phone: '' };
        this.snack.open(`${e.guest_name} added — token ${e.token}`, undefined, { duration: 3000 });
        this.reload();
      },
    );
  }

  protected notify(e: QueueEntry, tableId: string | null): void {
    this.run(e.id, this.api.notifyQueue(e.id, tableId), () => {
      this.snack.open(`${e.guest_name} notified.`, undefined, { duration: 2000 });
      this.reload();
    });
  }

  protected seat(e: QueueEntry, tableId: string): void {
    this.run(e.id, this.api.seatQueue(e.id, tableId), (seated) => {
      this.reload();
      this.dialog.open(CodeDialogComponent, { data: seated, width: '420px' });
    });
  }

  protected move(e: QueueEntry, dir: 'up' | 'down'): void {
    this.run(e.id, this.api.moveQueue(e.id, dir), (list) => this.entries.set(list));
  }

  protected end(e: QueueEntry, action: 'skip' | 'no-show' | 'cancel'): void {
    this.run(e.id, this.api.endQueue(e.id, action), () => this.reload());
  }

  protected printQr(): void {
    const w = window.open('', '_blank', 'width=480,height=640');
    if (!w || !this.qr()) return;
    const name = this.auth.activeTenant()?.tenant_name ?? '';
    w.document.write(
      `<html><head><title>Queue QR</title></head><body style="font-family:sans-serif;text-align:center;padding:2rem">` +
        `<h1>${escapeHtml(name)}</h1><p style="font-size:1.3rem">Scan to join the queue</p>` +
        `<img src="${this.qr()}" width="320" height="320" alt="QR code"/><p>${escapeHtml(this.queueUrl())}</p>` +
        `<script>window.onload=()=>window.print()</script></body></html>`,
    );
    w.document.close();
  }

  protected copyLink(): void {
    void navigator.clipboard?.writeText(this.queueUrl()).then(() =>
      this.snack.open('Queue link copied.', undefined, { duration: 2000 }),
    );
  }

  private loadTables(): void {
    const id = this.branchId();
    if (!id) return;
    this.ops.board(id).subscribe({ next: (b) => this.tables.set(b.tables), error: () => undefined });
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

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

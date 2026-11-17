import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { interval } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import {
  BookingOptions,
  BookingsService,
  QUEUE_STATUS_LABEL,
  QueueEntry,
  WaitTime,
} from '../../../core/bookings/bookings.service';
import { ApiError } from '../../../core/http/api-error';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';

const ACTIVE = ['waiting', 'notified'];

/** Join the walk-in queue and follow your token live (PRD §12 Queue Management). */
@Component({
  selector: 'wl-storefront-queue',
  imports: [FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './queue.page.html',
  styleUrl: './queue.page.scss',
})
export class StorefrontQueuePage implements OnInit {
  protected readonly ctx = inject(TenantContextService);
  protected readonly auth = inject(AuthService);
  private readonly api = inject(BookingsService);
  private readonly realtime = inject(RealtimeService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly statusLabel = QUEUE_STATUS_LABEL;
  protected readonly options = signal<BookingOptions[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly wait = signal<WaitTime | null>(null);
  protected readonly entry = signal<QueueEntry | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly loaded = signal(false);
  protected party = 2;
  protected name = '';

  protected readonly branch = computed(() => this.options().find((o) => o.branch_id === this.branchId()) ?? null);
  protected readonly queueBranches = computed(() => this.options().filter((o) => o.accepts_queue));
  protected readonly active = computed(() => {
    const e = this.entry();
    return !!e && ACTIVE.includes(e.status);
  });
  private watched: { tenant: string; branch: string } | null = null;

  ngOnInit(): void {
    const slug = this.ctx.slug();
    if (!slug) return;
    this.name = this.auth.user()?.full_name ?? '';
    this.api.options(slug).subscribe({
      next: (opts) => {
        this.options.set(opts);
        const first = opts.find((o) => o.accepts_queue) ?? opts[0];
        if (first) this.selectBranch(first.branch_id);
        this.loaded.set(true);
      },
      error: (e: ApiError) => {
        this.error.set(e.message);
        this.loaded.set(true);
      },
    });
    if (this.auth.isAuthenticated()) {
      this.api.myBookings().subscribe((mine) => {
        const current = mine.queue.find((q) => q.restaurant_slug === slug && ACTIVE.includes(q.status));
        if (current) this.track(current);
      });
      void this.realtime.subscribeUser();
    }
    const offQueue = this.realtime.on<{ branch_id: string }>('queue.changed', (e) => {
      if (e.branch_id === this.branchId()) this.refresh();
    });
    const offNote = this.realtime.on('notification', () => this.refresh());
    interval(30_000)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.refresh());
    this.destroyRef.onDestroy(() => {
      offQueue();
      offNote();
      this.unwatch();
    });
  }

  protected selectBranch(id: string): void {
    this.branchId.set(id);
    this.watch(id);
    this.loadWait();
  }

  /** Shared/incognito windows share one sign-in: let the guest switch to their own account. */
  protected switchAccount(): void {
    this.auth.logout(`/login?returnUrl=${encodeURIComponent(`/r/${this.ctx.slug()}/queue`)}`);
  }

  protected signIn(): void {
    void this.router.navigate(['/login'], { queryParams: { returnUrl: `/r/${this.ctx.slug()}/queue` } });
  }

  protected join(): void {
    const slug = this.ctx.slug();
    const branch = this.branchId();
    if (!slug || !branch) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.joinQueue(slug, { branch_id: branch, party_size: this.party, guest_name: this.name.trim() || undefined }).subscribe({
      next: (e) => {
        this.busy.set(false);
        this.track(e);
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.error.set(e.message);
      },
    });
  }

  protected leave(): void {
    const e = this.entry();
    if (!e) return;
    this.busy.set(true);
    this.api.leaveQueue(e.id).subscribe({
      next: (left) => {
        this.busy.set(false);
        this.entry.set(left);
        this.loadWait();
      },
      error: (err: ApiError) => {
        this.busy.set(false);
        this.error.set(err.message);
      },
    });
  }

  protected rejoin(): void {
    this.entry.set(null);
    this.loadWait();
  }

  private track(e: QueueEntry): void {
    this.entry.set(e);
    if (e.branch_id !== this.branchId()) this.selectBranch(e.branch_id);
  }

  private refresh(): void {
    const e = this.entry();
    if (e && ACTIVE.includes(e.status)) {
      this.api.myQueueEntry(e.id).subscribe({ next: (x) => this.entry.set(x), error: () => undefined });
    }
    this.loadWait();
  }

  private loadWait(): void {
    const slug = this.ctx.slug();
    const branch = this.branchId();
    if (!slug || !branch) return;
    this.api.waitTime(slug, branch, this.party).subscribe({ next: (w) => this.wait.set(w), error: () => this.wait.set(null) });
  }

  private watch(branch: string): void {
    const tenant = this.ctx.restaurant()?.id;
    if (!tenant || (this.watched?.branch === branch && this.watched.tenant === tenant)) return;
    this.unwatch();
    this.watched = { tenant, branch };
    void this.realtime.subscribeQueue(tenant, branch);
  }

  private unwatch(): void {
    if (this.watched) this.realtime.unsubscribeQueue(this.watched.tenant, this.watched.branch);
    this.watched = null;
  }

  protected partyChanged(): void {
    this.loadWait();
  }
}

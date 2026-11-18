import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar } from '@angular/material/snack-bar';
import { RouterLink } from '@angular/router';
import QRCode from 'qrcode';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { OperationsService, TableQrSheet } from '../../../core/restaurant/operations.service';
import { Branch } from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/**
 * One QR code per table, to print and stand on the table. Scanning opens the menu for that table:
 * a free table can be opened by the guest (self-seating), a taken one is joined with its PIN.
 */
@Component({
  selector: 'wl-table-qr',
  imports: [RouterLink, MatButtonModule, MatIconModule, MatSlideToggleModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .page-head { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; justify-content: space-between; margin-bottom: 1rem; }
    .page-head h1 { margin: 0; }
    .muted { color: var(--wl-muted, #6b6b6b); margin: 0.2rem 0 0; }
    .tools { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; margin-bottom: 1rem; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; }
    .card { border: 1px solid var(--wl-line); border-radius: 14px; padding: 1rem; text-align: center; background: #fff; color: #1d1d1d; break-inside: avoid; }
    .card img { width: 180px; height: 180px; display: block; margin: 0.4rem auto; }
    .card .rest { font-weight: 600; margin: 0; }
    .card .label { font-size: 1.6rem; font-weight: 800; margin: 0.1rem 0; }
    .card .hint { font-size: 0.85rem; margin: 0; }
    .card .url { font-size: 0.7rem; color: #666; word-break: break-all; margin: 0.3rem 0 0; }
    .card .row { display: flex; justify-content: center; gap: 0.25rem; margin-top: 0.4rem; }
    select { font: inherit; padding: 0.3rem 0.4rem; }
    @media print {
      .page-head, .tools, .no-print { display: none !important; }
      .grid { grid-template-columns: repeat(3, 1fr); gap: 0.5cm; }
      .card { border: 1px dashed #999; }
    }
  `,
  template: `
    <header class="page-head no-print">
      <div>
        <h1>Table QR codes</h1>
        <p class="muted">Print these and place one on each table. Guests scan to see the menu and order.</p>
      </div>
      <a mat-button routerLink="/restaurant-admin/tables"><mat-icon>arrow_back</mat-icon> Tables</a>
    </header>

    @if (error(); as e) {
      <wl-error-state title="Could not load the QR codes" [message]="e.message" [retryable]="false" />
    } @else if (!sheet()) {
      <wl-loading-state />
    } @else {
      @let s = sheet()!;
      <div class="tools">
        @if (branches().length > 1) {
          <select [value]="branchId() ?? ''" (change)="selectBranch($any($event.target).value)" aria-label="Branch">
            @for (b of branches(); track b.id) { <option [value]="b.id">{{ b.name }}</option> }
          </select>
        }
        @if (canConfigure()) {
          <mat-slide-toggle [checked]="s.self_seating" (change)="setSelfSeating($event.checked)" data-testid="self-seating">
            Guests can open a free table by scanning
          </mat-slide-toggle>
        }
        <button mat-flat-button type="button" (click)="print()" [disabled]="!s.tables.length" data-testid="print-qr">
          <mat-icon>print</mat-icon> Print all</button>
      </div>
      @if (!s.self_seating) {
        <p class="muted no-print">Self-seating is off: guests scanning a free table are asked to wait for staff, who give them the order ID and PIN.</p>
      }
      <div class="grid">
        @for (t of s.tables; track t.table_id) {
          <article class="card" data-testid="qr-card">
            <p class="rest">{{ s.restaurant_name }}</p>
            <p class="label">Table {{ t.label }}</p>
            @if (images()[t.table_id]; as img) { <img [src]="img" [alt]="'QR code for table ' + t.label" /> }
            <p class="hint">Scan to see the menu &amp; order</p>
            <p class="url">{{ url(t.path) }}</p>
            @if (canConfigure()) {
              <div class="row no-print">
                <button mat-button type="button" (click)="rotate(t.table_id, t.label)" [disabled]="busy() === t.table_id" data-testid="qr-rotate">
                  <mat-icon>autorenew</mat-icon> New code</button>
              </div>
            }
          </article>
        } @empty {
          <p class="muted">No tables in this branch yet. Add them on the Tables page.</p>
        }
      </div>
    }
  `,
})
export class TableQrPage implements OnInit {
  private readonly ops = inject(OperationsService);
  private readonly tenancy = inject(TenancyService);
  private readonly auth = inject(AuthService);
  private readonly snack = inject(MatSnackBar);

  protected readonly branches = signal<Branch[]>([]);
  protected readonly branchId = signal<string | null>(null);
  protected readonly sheet = signal<TableQrSheet | null>(null);
  protected readonly images = signal<Record<string, string>>({});
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null);
  protected readonly canConfigure = computed(() => this.auth.hasPermission('tables.configure'));

  ngOnInit(): void {
    this.tenancy.restaurantMe().subscribe({
      next: (me) => {
        const active = me.branches.filter((b) => b.is_active);
        this.branches.set(active);
        const first = active.find((b) => b.is_primary) ?? active[0];
        if (first) this.selectBranch(first.id);
        else this.sheet.set({ branch_id: '', branch_name: '', restaurant_name: '', slug: '', self_seating: true, tables: [] });
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected selectBranch(id: string): void {
    this.branchId.set(id);
    this.sheet.set(null);
    this.ops.tableQr(id).subscribe({ next: (s) => this.show(s), error: (e: ApiError) => this.error.set(e) });
  }

  protected url(path: string): string {
    return `${location.origin}${path}`;
  }

  protected rotate(tableId: string, label: string): void {
    if (!confirm(`Make a new QR code for table ${label}? The printed one stops working.`)) return;
    this.busy.set(tableId);
    this.ops.rotateTableQr(tableId).subscribe({
      next: (s) => {
        this.busy.set(null);
        this.show(s);
        this.snack.open(`New QR code for table ${label} — print it again.`, undefined, { duration: 3000 });
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        this.snack.open(e.message, 'OK', { duration: 5000 });
      },
    });
  }

  protected setSelfSeating(enabled: boolean): void {
    this.ops.setSelfSeating(enabled).subscribe({
      next: (r) => this.sheet.update((s) => (s ? { ...s, self_seating: r.enabled } : s)),
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  protected print(): void {
    window.print();
  }

  private show(s: TableQrSheet): void {
    this.sheet.set(s);
    void Promise.all(
      s.tables.map(async (t) => [t.table_id, await QRCode.toDataURL(this.url(t.path), { margin: 1, width: 360 })] as const),
    ).then((pairs) => this.images.set(Object.fromEntries(pairs)));
  }
}

import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';

import { ApiError } from '../../../core/http/api-error';
import { InventoryService, MOVEMENT_LABEL, Movement, StockRow, qty } from '../../../core/inventory/inventory.service';

/** The ledger of one item at one branch (PRD §8.2 "inventory history"). */
@Component({
  selector: 'wl-history-dialog',
  imports: [MatDialogModule, MatButtonModule, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './inventory-forms.scss',
  template: `
    <h2 mat-dialog-title>{{ data.row.name }} — history</h2>
    <mat-dialog-content>
      @if (error(); as e) { <p class="err">{{ e }}</p> }
      @if (rows(); as list) {
        @if (!list.length) { <p class="hint">No stock recorded yet.</p> }
        @else {
          <table class="table" data-testid="history">
            <thead><tr><th>When</th><th>What</th><th class="num">Change</th><th class="num">Balance</th><th>Reason / by</th></tr></thead>
            <tbody>
              @for (m of list; track m.id) {
                <tr>
                  <td>{{ m.created_at | date: 'd MMM, HH:mm' }}</td>
                  <td>{{ label[m.type] }}</td>
                  <td class="num" [class.neg]="+m.quantity < 0" [class.pos]="+m.quantity > 0">
                    {{ +m.quantity > 0 ? '+' : '' }}{{ qty(m.quantity) }} {{ m.unit }}</td>
                  <td class="num">{{ qty(m.balance_after) }}</td>
                  <td>{{ m.reason }}@if (m.expiry_date) { · expires {{ m.expiry_date | date: 'd MMM' }} }
                    @if (m.actor_name) { <br /><small class="hint">{{ m.actor_name }}</small> }</td>
                </tr>
              }
            </tbody>
          </table>
        }
      } @else { <p class="hint">Loading…</p> }
    </mat-dialog-content>
    <mat-dialog-actions align="end"><button mat-button mat-dialog-close>Close</button></mat-dialog-actions>
  `,
})
export class HistoryDialogComponent implements OnInit {
  protected readonly data = inject<{ branchId: string; row: StockRow }>(MAT_DIALOG_DATA);
  private readonly api = inject(InventoryService);
  protected readonly label = MOVEMENT_LABEL;
  protected readonly qty = qty;
  protected readonly rows = signal<Movement[] | null>(null);
  protected readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.api
      .movements(this.data.branchId, { item_id: this.data.row.item_id, limit: 300 })
      .subscribe({ next: (r) => this.rows.set(r), error: (e: ApiError) => this.error.set(e.message) });
  }
}

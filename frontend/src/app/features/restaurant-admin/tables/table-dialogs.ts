import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { BoardTable, Seated } from '../../../core/restaurant/operations.service';

// ---------- seat guests ----------

export interface SeatDialogData {
  table: BoardTable;
}
export interface SeatDialogResult {
  partySize: number;
  guestName: string;
}

@Component({
  selector: 'wl-seat-dialog',
  imports: [ReactiveFormsModule, MatDialogModule, MatFormFieldModule, MatInputModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>Seat guests at {{ data.table.label }}</h2>
    <mat-dialog-content>
      <form [formGroup]="form" id="seat-form" (ngSubmit)="save()" class="form">
        <mat-form-field appearance="outline">
          <mat-label>Party size</mat-label>
          <input matInput type="number" min="1" max="100" formControlName="partySize" cdkFocusInitial />
          <mat-hint>Table seats {{ data.table.capacity }}</mat-hint>
          <mat-error>1 to 100 guests</mat-error>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Guest name (optional)</mat-label>
          <input matInput formControlName="guestName" maxlength="80" />
        </mat-form-field>
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="undefined">Cancel</button>
      <button mat-flat-button type="submit" form="seat-form">Seat guests</button>
    </mat-dialog-actions>
  `,
  styles: `
    .form {
      display: grid;
      gap: 0.2rem;
      padding-top: 0.4rem;
      min-width: min(340px, 80vw);
    }
  `,
})
export class SeatDialogComponent {
  protected readonly data = inject<SeatDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<SeatDialogComponent, SeatDialogResult>);
  protected readonly form = inject(NonNullableFormBuilder).group({
    partySize: [Math.min(2, this.data.table.capacity), [Validators.required, Validators.min(1), Validators.max(100)]],
    guestName: [''],
  });

  protected save(): void {
    if (this.form.invalid) return this.form.markAllAsTouched();
    this.ref.close(this.form.getRawValue());
  }
}

// ---------- code + PIN ----------

@Component({
  selector: 'wl-code-dialog',
  imports: [MatDialogModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>Tell the guests</h2>
    <mat-dialog-content>
      <p class="hint">They open this restaurant on WaitLess, choose "Have an order ID?" and enter:</p>
      <dl class="codes">
        <div><dt>Order ID</dt><dd data-testid="session-code">{{ data.session.public_code }}</dd></div>
        <div><dt>PIN</dt><dd data-testid="session-pin">{{ data.pin }}</dd></div>
      </dl>
      <p class="small">The PIN is shown only now. You can issue a new one from the table later.</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-flat-button type="button" [mat-dialog-close]="true" cdkFocusInitial>Done</button>
    </mat-dialog-actions>
  `,
  styles: `
    .hint {
      color: var(--wl-text-soft);
    }
    .codes {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin: 1rem 0;
      div {
        padding: 0.8rem;
        border-radius: 12px;
        background: var(--wl-surface-alt);
        text-align: center;
      }
      dt {
        font-size: 0.75rem;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: var(--wl-muted);
      }
      dd {
        margin: 0.2rem 0 0;
        font: 700 2rem/1.1 ui-monospace, Consolas, monospace;
        letter-spacing: 0.08em;
      }
    }
    .small {
      font-size: 0.8rem;
      color: var(--wl-muted);
    }
  `,
})
export class CodeDialogComponent {
  protected readonly data = inject<Seated>(MAT_DIALOG_DATA);
}

// ---------- move guests ----------

export interface TransferDialogData {
  from: BoardTable;
  free: BoardTable[];
}

@Component({
  selector: 'wl-transfer-dialog',
  imports: [MatDialogModule, MatButtonModule, MatFormFieldModule, MatSelectModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>Move guests from {{ data.from.label }}</h2>
    <mat-dialog-content>
      @if (data.free.length) {
        <mat-form-field appearance="outline" class="full">
          <mat-label>To table</mat-label>
          <mat-select cdkFocusInitial (selectionChange)="choice.set($event.value)">
            @for (t of data.free; track t.id) {
              <mat-option [value]="t.id">{{ t.label }} · {{ t.capacity }} seats{{ t.section_name ? ' · ' + t.section_name : '' }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
      } @else {
        <p>No free table right now.</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="undefined">Cancel</button>
      @if (data.free.length) {
        <button mat-flat-button type="button" [disabled]="!choice()" (click)="ref.close(choice()!)">Move</button>
      }
    </mat-dialog-actions>
  `,
  styles: `
    .full {
      width: min(360px, 80vw);
    }
  `,
})
export class TransferDialogComponent {
  protected readonly data = inject<TransferDialogData>(MAT_DIALOG_DATA);
  protected readonly ref = inject(MatDialogRef<TransferDialogComponent, string>);
  protected readonly choice = signal<string | null>(null);
}

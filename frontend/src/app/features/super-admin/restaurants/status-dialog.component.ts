import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

import { REASON_REQUIRED, StatusAction } from '../../../core/tenancy/tenancy.models';

export interface StatusDialogData {
  action: StatusAction;
  restaurantName: string;
}

const COPY: Record<StatusAction, { title: string; text: string; confirm: string }> = {
  approve: { title: 'Approve restaurant', text: 'The owner gets full access and the restaurant can go live.', confirm: 'Approve' },
  reject: { title: 'Reject registration', text: 'The owner will see this reason.', confirm: 'Reject' },
  activate: { title: 'Re-activate restaurant', text: 'Restores access for the owner and staff.', confirm: 'Activate' },
  suspend: { title: 'Suspend restaurant', text: 'Staff lose access to operations until re-activated.', confirm: 'Suspend' },
  deactivate: { title: 'Deactivate restaurant', text: 'The restaurant is closed on WaitLess.', confirm: 'Deactivate' },
};

/** Confirms a status change; asks for a reason where the backend requires one. Closes with the reason (or ''). */
@Component({
  selector: 'wl-status-dialog',
  imports: [ReactiveFormsModule, MatDialogModule, MatButtonModule, MatFormFieldModule, MatInputModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ copy.title }}</h2>
    <mat-dialog-content>
      <p>
        <b>{{ data.restaurantName }}</b> — {{ copy.text }}
      </p>
      @if (needsReason) {
        <mat-form-field appearance="outline" class="reason">
          <mat-label>Reason</mat-label>
          <textarea matInput rows="3" [formControl]="reason" cdkFocusInitial></textarea>
          <mat-error>A reason is required</mat-error>
        </mat-form-field>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <!-- an empty mat-dialog-close attribute would close with '' and confirm the action -->
      <button mat-button [mat-dialog-close]="undefined" type="button">Cancel</button>
      <button mat-flat-button type="button" (click)="confirm()">{{ copy.confirm }}</button>
    </mat-dialog-actions>
  `,
  styles: `
    .reason {
      width: 100%;
      margin-top: 0.6rem;
    }
  `,
})
export class StatusDialogComponent {
  protected readonly data = inject<StatusDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<StatusDialogComponent, string>);
  protected readonly copy = COPY[this.data.action];
  protected readonly needsReason = REASON_REQUIRED.has(this.data.action);
  protected readonly reason = inject(NonNullableFormBuilder).control('', this.needsReason ? [Validators.required] : []);

  protected confirm(): void {
    if (this.reason.invalid) {
      this.reason.markAsTouched();
      return;
    }
    this.ref.close(this.reason.value.trim());
  }
}

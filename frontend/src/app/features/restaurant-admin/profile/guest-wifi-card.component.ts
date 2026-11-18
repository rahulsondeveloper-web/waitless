import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar } from '@angular/material/snack-bar';

import { ApiError } from '../../../core/http/api-error';
import { GuestServiceApi } from '../../../core/ordering/guest-service.service';

/** Restaurant Wi-Fi for seated guests (shown on their phone once they have joined a table). */
@Component({
  selector: 'wl-guest-wifi-card',
  imports: [FormsModule, MatFormFieldModule, MatInputModule, MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0 1rem; }
    @media (max-width: 640px) { .row { grid-template-columns: 1fr; } }
    .muted { color: var(--mat-sys-on-surface-variant, #666); margin: 0 0 0.8rem; }
    .actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
  `,
  template: `
    <section class="card" aria-labelledby="h-wifi" data-testid="guest-wifi-card">
      <h2 id="h-wifi">Guest Wi-Fi</h2>
      <p class="muted">Seated guests see a "Restaurant Wi-Fi" button with these details. Only guests who have joined a table can see them.</p>
      <form (ngSubmit)="save()" class="row">
        <mat-form-field appearance="outline">
          <mat-label>Network name</mat-label>
          <input matInput name="wifiName" [(ngModel)]="name" maxlength="64" [disabled]="!canManage()" data-testid="wifi-name" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Password</mat-label>
          <input matInput name="wifiPassword" [(ngModel)]="password" maxlength="64" [disabled]="!canManage()"
                 [type]="reveal() ? 'text' : 'password'" autocomplete="off" data-testid="wifi-password" />
          <button mat-icon-button matSuffix type="button" (click)="reveal.set(!reveal())"
                  [attr.aria-label]="reveal() ? 'Hide password' : 'Show password'">
            <mat-icon>{{ reveal() ? 'visibility_off' : 'visibility' }}</mat-icon>
          </button>
        </mat-form-field>
        @if (canManage()) {
          <div class="actions" style="grid-column: 1 / -1">
            @if (name || password) {
              <button mat-button type="button" (click)="clear()" [disabled]="busy()">Remove</button>
            }
            <button mat-flat-button type="submit" [disabled]="busy()" data-testid="wifi-save">Save Wi-Fi</button>
          </div>
        }
      </form>
    </section>
  `,
})
export class GuestWifiCardComponent implements OnInit {
  readonly canManage = input(false);
  private readonly api = inject(GuestServiceApi);
  private readonly snack = inject(MatSnackBar);
  protected name = '';
  protected password = '';
  protected readonly reveal = signal(false);
  protected readonly busy = signal(false);

  ngOnInit(): void {
    this.api.getWifi().subscribe({
      next: (w) => {
        this.name = w.name;
        this.password = w.password;
      },
      error: () => undefined,
    });
  }

  protected clear(): void {
    this.name = '';
    this.password = '';
    this.save();
  }

  protected save(): void {
    this.busy.set(true);
    this.api.setWifi({ name: this.name.trim(), password: this.password }).subscribe({
      next: () => {
        this.busy.set(false);
        this.snack.open('Guest Wi-Fi saved.', undefined, { duration: 2500 });
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.snack.open(e.message, 'OK', { duration: 5000 });
      },
    });
  }
}

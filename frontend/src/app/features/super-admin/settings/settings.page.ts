import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';

import { ApiError } from '../../../core/http/api-error';
import { PlatformSettings, SuperAdminService, Template } from '../../../core/platform-admin/super-admin.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** System settings, integration status and notification wording (PRD §16 "system / integration settings"). */
@Component({
  selector: 'wl-sa-settings',
  imports: [FormsModule, MatButtonModule, MatTabsModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  styles: `
    form.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.8rem; max-width: 900px; margin-top: 1rem; }
    .full { grid-column: 1 / -1; }
    .tpl { display: grid; grid-template-columns: 14rem 1fr 1.6fr auto auto; gap: 0.5rem; align-items: end; padding: 0.5rem 0; border-bottom: 1px solid var(--wl-line); }
    @media (max-width: 860px) { .tpl { grid-template-columns: 1fr; } }
  `,
  template: `
    <header class="page-head"><div><h1>Settings</h1><p class="muted">Platform-wide settings for WaitLess.</p></div></header>
    @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
    @else if (!data()) { <wl-loading-state /> }
    @else {
      <mat-tab-group animationDuration="150ms" mat-stretch-tabs="false">
        <mat-tab label="System">
          <form class="grid" (ngSubmit)="save()">
            <label class="field"><span>Grace period after an unpaid renewal (days)</span>
              <input type="number" min="0" max="60" name="g" [(ngModel)]="s.grace_days" data-testid="set-grace" /></label>
            <label class="field"><span>GST on WaitLess invoices (%)</span><input type="number" min="0" max="28" name="tax" [(ngModel)]="s.saas_tax_pct" /></label>
            <label class="field"><span>Invoice due after (days)</span><input type="number" min="0" max="60" name="due" [(ngModel)]="s.invoice_due_days" /></label>
            <label class="field"><span>Support e-mail</span><input type="email" name="se" [(ngModel)]="s.support_email" /></label>
            <label class="field"><span>Support phone</span><input name="sp" [(ngModel)]="s.support_phone" /></label>
            <label class="field full"><span>Banner on the website (e.g. planned maintenance) — empty to hide</span>
              <input name="mb" [(ngModel)]="s.maintenance_banner" maxlength="200" data-testid="set-banner" /></label>
            <label class="check full"><input type="checkbox" name="ar" [(ngModel)]="s.allow_registration" /> Restaurants can register themselves</label>
            <div class="full"><button mat-flat-button type="submit" data-testid="save-platform-settings">Save</button></div>
          </form>
        </mat-tab>
        <mat-tab label="Integrations">
          <table class="table" style="max-width: 900px; margin-top: 1rem" data-testid="integrations">
            <thead><tr><th>Service</th><th>Provider</th><th>Status</th><th>Note</th></tr></thead>
            <tbody>
              @for (i of data()!.integrations; track i.name) {
                <tr><td><b>{{ i.name }}</b></td><td>{{ i.provider }}</td>
                  <td><span class="badge" [attr.data-tone]="i.status === 'connected' ? 'ok' : i.status === 'test mode' ? 'warn' : 'bad'">{{ i.status }}</span></td>
                  <td class="muted">{{ i.note ?? '' }}</td></tr>
              }
            </tbody>
          </table>
          <p class="muted">Keys are set on the server (.env) and are never shown here.</p>
        </mat-tab>
        <mat-tab label="Notifications">
          <p class="muted" style="margin-top: 1rem">Wording of the messages guests receive. <code>{{ '{' }}title{{ '}' }}</code> and
            <code>{{ '{' }}body{{ '}' }}</code> insert the standard text; switch an event off to stop sending it.</p>
          @for (t of templates(); track t.event) {
            <form class="tpl" (ngSubmit)="saveTemplate(t)" [attr.data-testid]="'tpl-' + t.event">
              <span><b>{{ t.label }}</b><br /><small class="muted">{{ t.event }}</small></span>
              <label class="field"><span>Title</span><input [name]="'t' + t.event" [(ngModel)]="t.title" maxlength="120" /></label>
              <label class="field"><span>Text</span><input [name]="'b' + t.event" [(ngModel)]="t.body" maxlength="500" /></label>
              <label class="check"><input type="checkbox" [name]="'e' + t.event" [(ngModel)]="t.enabled" /> On</label>
              <button mat-stroked-button type="submit">Save</button>
            </form>
          }
        </mat-tab>
      </mat-tab-group>
    }
  `,
})
export class SaSettingsPage implements OnInit {
  private readonly api = inject(SuperAdminService);
  private readonly snack = inject(MatSnackBar);
  protected readonly data = signal<PlatformSettings | null>(null);
  protected readonly templates = signal<Template[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected s = {} as PlatformSettings['settings'];

  ngOnInit(): void {
    this.load();
    this.api.templates().subscribe((t) => this.templates.set(t));
  }

  protected load(): void {
    this.api.settings().subscribe({
      next: (d) => {
        this.data.set(d);
        this.s = { ...d.settings };
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected save(): void {
    const body = { ...this.s, grace_days: +this.s.grace_days, invoice_due_days: +this.s.invoice_due_days, saas_tax_pct: String(this.s.saas_tax_pct) };
    this.api.saveSettings(body).subscribe({
      next: (d) => {
        this.data.set(d);
        this.s = { ...d.settings };
        this.snack.open('Settings saved.', undefined, { duration: 2000 });
      },
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }

  protected saveTemplate(t: Template): void {
    this.api.saveTemplate(t).subscribe({
      next: (list) => {
        this.templates.set(list);
        this.snack.open(`"${t.label}" saved.`, undefined, { duration: 2000 });
      },
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 5000 }),
    });
  }
}

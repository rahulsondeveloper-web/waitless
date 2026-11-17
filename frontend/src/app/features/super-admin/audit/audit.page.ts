import { DatePipe, JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';

import { ApiError } from '../../../core/http/api-error';
import { AuditEntry, SuperAdminService } from '../../../core/platform-admin/super-admin.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Audit log (PRD §16 "platform audit logs, administrator activity"): who did what, when, with the change. */
@Component({
  selector: 'wl-sa-audit',
  imports: [DatePipe, JsonPipe, FormsModule, MatButtonModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  styles: `
    details summary { cursor: pointer; color: var(--wl-primary); }
    pre { max-width: 520px; overflow: auto; font-size: 0.78rem; background: var(--wl-surface-alt, #f5f6f8); padding: 0.5rem; border-radius: 8px; }
    .pager { display: flex; gap: 0.5rem; align-items: center; justify-content: flex-end; margin-top: 0.6rem; }
  `,
  template: `
    <header class="page-head"><div><h1>Audit log</h1><p class="muted">Every sensitive change on the platform, newest first.</p></div></header>
    <form class="bar" (ngSubmit)="page = 1; load()">
      <label class="field"><span>Action contains</span><input name="a" [(ngModel)]="action" placeholder="e.g. refund, plan, discount" data-testid="audit-action" /></label>
      <label class="field"><span>From</span><input type="date" name="f" [(ngModel)]="from" /></label>
      <label class="field"><span>To</span><input type="date" name="t" [(ngModel)]="to" /></label>
      <label class="check"><input type="checkbox" name="o" [(ngModel)]="adminsOnly" /> WaitLess administrators only</label>
      <button mat-flat-button type="submit">Filter</button>
    </form>
    @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
    @else if (!items()) { <wl-loading-state /> }
    @else {
      <div class="scroll">
        <table class="table" data-testid="audit-table">
          <thead><tr><th>When</th><th>Who</th><th>Restaurant</th><th>Action</th><th>Details</th></tr></thead>
          <tbody>
            @for (e of items(); track e.id) {
              <tr>
                <td>{{ e.created_at | date: 'd MMM y, HH:mm:ss' }}</td>
                <td>{{ e.actor_name ?? 'System' }}@if (e.actor_is_admin) { <span class="badge">Admin</span> }
                  @if (e.ip) { <br /><small class="muted">{{ e.ip }}</small> }</td>
                <td>{{ e.tenant_name ?? '—' }}</td>
                <td><b>{{ e.action }}</b><br /><small class="muted">{{ e.entity }}{{ e.entity_id ? ' · ' + e.entity_id.slice(0, 8) : '' }}</small></td>
                <td>@if (e.reason) { <p>Reason: {{ e.reason }}</p> }
                  @if (e.diff) { <details><summary>Change</summary><pre>{{ e.diff | json }}</pre></details> }</td>
              </tr>
            } @empty { <tr><td colspan="5" class="muted">Nothing matches.</td></tr> }
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span class="muted">{{ total() }} entries</span>
        <button mat-button (click)="go(-1)" [disabled]="page <= 1">Newer</button>
        <span>Page {{ page }}</span>
        <button mat-button (click)="go(1)" [disabled]="page * 50 >= total()">Older</button>
      </div>
    }
  `,
})
export class SaAuditPage implements OnInit {
  private readonly api = inject(SuperAdminService);
  protected readonly items = signal<AuditEntry[] | null>(null);
  protected readonly total = signal(0);
  protected readonly error = signal<ApiError | null>(null);
  protected action = '';
  protected from = '';
  protected to = '';
  protected adminsOnly = false;
  protected page = 1;

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.items.set(null);
    this.api
      .audit({ action: this.action || undefined, from: this.from || undefined, to: this.to || undefined, admins_only: this.adminsOnly || undefined, page: this.page, page_size: 50 })
      .subscribe({
        next: (r) => {
          this.items.set(r.items);
          this.total.set(r.total);
        },
        error: (e: ApiError) => this.error.set(e),
      });
  }

  protected go(step: number): void {
    this.page = Math.max(1, this.page + step);
    this.load();
  }
}

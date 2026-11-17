import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar } from '@angular/material/snack-bar';

import { Ticket } from '../../../core/analytics/analytics.service';
import { ApiError } from '../../../core/http/api-error';
import { SuperAdminService } from '../../../core/platform-admin/super-admin.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

const SOURCE: Record<string, string> = { contact_form: 'Website form', restaurant: 'Restaurant', admin: 'Admin' };
const TONE: Record<string, string> = { urgent: 'bad', high: 'warn', normal: '', low: '' };

/** Support desk (PRD §16): requests from the website and restaurants, priorities, owners, internal notes. */
@Component({
  selector: 'wl-sa-support',
  imports: [DatePipe, FormsModule, MatButtonModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  styles: `
    .layout { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; gap: 1rem; align-items: start; }
    @media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
    .list { display: grid; gap: 0.4rem; }
    .item { text-align: left; font: inherit; color: inherit; background: var(--wl-surface); border: 1px solid var(--wl-line); border-radius: 10px; padding: 0.6rem 0.75rem; cursor: pointer; display: grid; gap: 0.15rem; }
    .item[aria-current='true'] { border-color: var(--wl-primary); }
    .item p { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--wl-muted); }
    .msg { white-space: pre-wrap; background: var(--wl-surface-alt, #f5f6f8); border-radius: 10px; padding: 0.7rem; }
    .notes { list-style: none; padding: 0; display: grid; gap: 0.5rem; }
    .notes li { border-left: 3px solid #e0a53b; padding: 0.2rem 0.6rem; }
    .controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.6rem; margin: 0.8rem 0; }
  `,
  template: `
    <header class="page-head"><div><h1>Support</h1><p class="muted">Requests from the website and from restaurants.</p></div>
      <div class="bar" style="margin: 0">
        <label class="field"><span>Show</span>
          <select [(ngModel)]="status" (ngModelChange)="load()"><option value="active">Open &amp; in progress</option><option value="">All</option>
            <option value="resolved">Resolved</option><option value="closed">Closed</option></select></label>
        <label class="field"><span>Search</span><input type="search" [(ngModel)]="q" (keyup.enter)="load()" /></label>
      </div>
    </header>
    @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
    @else if (!tickets()) { <wl-loading-state /> }
    @else {
      <div class="layout">
        <div class="list" data-testid="tickets">
          @for (t of tickets(); track t.id) {
            <button type="button" class="item" [attr.aria-current]="open()?.id === t.id" (click)="select(t.id)" data-testid="ticket-item">
              <span><b>{{ t.tenant_name ?? t.name }}</b> · <span class="muted small">{{ source[t.source] }} · {{ t.created_at | date: 'd MMM HH:mm' }}</span></span>
              <span><span class="badge" [attr.data-tone]="tone[t.priority]">{{ t.priority }}</span> <span class="badge">{{ t.status.replace('_', ' ') }}</span>
                @if (t.assigned_to_name) { <span class="muted small">· {{ t.assigned_to_name }}</span> }</span>
              <p>{{ t.message }}</p>
            </button>
          } @empty { <p class="muted">No tickets here. 🎉</p> }
        </div>
        @if (open(); as t) {
          <section class="panel" data-testid="ticket-detail">
            <h2>{{ t.topic.replace('_', ' ') }} · {{ t.tenant_name ?? 'Website visitor' }}</h2>
            <p class="muted small">{{ t.name }} · <a [href]="'mailto:' + t.email">{{ t.email }}</a>{{ t.phone ? ' · ' + t.phone : '' }} · {{ t.created_at | date: 'd MMM y, HH:mm' }}</p>
            <p class="msg">{{ t.message }}</p>
            <div class="controls">
              <label class="field"><span>Status</span>
                <select [ngModel]="t.status" (ngModelChange)="update({ status: $event })" data-testid="ticket-status">
                  <option value="open">Open</option><option value="in_progress">In progress</option><option value="resolved">Resolved</option><option value="closed">Closed</option>
                </select></label>
              <label class="field"><span>Priority</span>
                <select [ngModel]="t.priority" (ngModelChange)="update({ priority: $event })">
                  <option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option>
                </select></label>
              <label class="field"><span>Owner</span>
                <select [ngModel]="t.assigned_to_id ?? ''" (ngModelChange)="update({ assigned_to_id: $event || null })">
                  <option value="">Nobody</option>
                  @for (a of admins(); track a.id) { <option [value]="a.id">{{ a.name }}</option> }
                </select></label>
            </div>
            <h3>Internal notes</h3>
            <ul class="notes">
              @for (n of t.notes ?? []; track n.id) { <li><small class="muted">{{ n.author }} · {{ n.created_at | date: 'd MMM HH:mm' }}</small><br />{{ n.body }}</li> }
              @empty { <li class="muted">No notes yet. Notes are never shown to the restaurant.</li> }
            </ul>
            <form (ngSubmit)="note()" class="bar">
              <label class="field grow"><span>Add a note</span><input name="n" [(ngModel)]="noteText" maxlength="4000" data-testid="note-text" /></label>
              <button mat-flat-button type="submit" [disabled]="!noteText.trim()" data-testid="note-add">Add</button>
            </form>
          </section>
        }
      </div>
    }
  `,
})
export class SaSupportPage implements OnInit {
  private readonly api = inject(SuperAdminService);
  private readonly snack = inject(MatSnackBar);
  protected readonly source = SOURCE;
  protected readonly tone = TONE;
  protected readonly tickets = signal<Ticket[] | null>(null);
  protected readonly open = signal<Ticket | null>(null);
  protected readonly admins = signal<{ id: string; name: string }[]>([]);
  protected readonly error = signal<ApiError | null>(null);
  protected status = 'active';
  protected q = '';
  protected noteText = '';

  ngOnInit(): void {
    this.api.admins().subscribe((a) => this.admins.set(a));
    this.load();
  }

  protected load(): void {
    this.api.tickets(this.status || undefined, this.q || undefined).subscribe({ next: (t) => this.tickets.set(t), error: (e: ApiError) => this.error.set(e) });
  }

  protected select(id: string): void {
    this.api.ticket(id).subscribe((t) => this.open.set(t));
  }

  protected update(body: Partial<{ status: string; priority: string; assigned_to_id: string | null }>): void {
    const t = this.open();
    if (!t) return;
    this.api.updateTicket(t.id, body).subscribe({
      next: (r) => {
        this.open.set(r);
        this.load();
      },
      error: (e: ApiError) => this.snack.open(e.message, 'OK', { duration: 4000 }),
    });
  }

  protected note(): void {
    const t = this.open();
    if (!t) return;
    this.api.addNote(t.id, this.noteText).subscribe((r) => {
      this.noteText = '';
      this.open.set(r);
    });
  }
}

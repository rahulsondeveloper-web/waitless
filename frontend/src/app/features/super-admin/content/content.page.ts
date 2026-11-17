import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';

import { ApiError } from '../../../core/http/api-error';
import { ContentMap, SuperAdminService } from '../../../core/platform-admin/super-admin.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

const SECTIONS: { key: string; label: string; page: string }[] = [
  { key: 'home', label: 'Home — top of the page', page: '/' },
  { key: 'how_it_works', label: 'How it works', page: '/#how-it-works' },
  { key: 'features', label: 'Features', page: '/#features' },
  { key: 'for_restaurants', label: 'For restaurants', page: '/#for-restaurants' },
  { key: 'about', label: 'About us', page: '/about' },
  { key: 'contact', label: 'Contact details', page: '/contact' },
  { key: 'branding', label: 'Platform branding', page: '/' },
  { key: 'terms', label: 'Terms of use', page: '/terms' },
  { key: 'privacy', label: 'Privacy policy', page: '/privacy' },
];
const LONG = new Set(['lead', 'body', 'vision', 'mission', 'text', 'address']);

type Field =
  | { key: string; kind: 'text' | 'long'; value: string }
  | { key: string; kind: 'list'; value: string }
  | { key: string; kind: 'rows'; value: Record<string, string>[]; cols: string[] };

/** Website content (PRD §16): every section of the public WaitLess site, edited without a deploy. */
@Component({
  selector: 'wl-sa-content',
  imports: [FormsModule, MatButtonModule, MatIconModule, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrls: ['../super-admin.scss'],
  styles: `
    .layout { display: grid; grid-template-columns: 240px 1fr; gap: 1rem; align-items: start; }
    @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
    nav { display: grid; gap: 0.25rem; }
    nav button { text-align: left; font: inherit; padding: 0.5rem 0.7rem; border-radius: 8px; border: 1px solid transparent; background: none; cursor: pointer; color: var(--wl-text); }
    nav button[aria-current='true'] { border-color: var(--wl-primary); background: color-mix(in srgb, var(--wl-primary) 8%, transparent); font-weight: 600; }
    form { display: grid; gap: 0.8rem; }
    .row { display: grid; grid-template-columns: 9rem 1fr 2fr auto; gap: 0.4rem; align-items: end; }
    @media (max-width: 600px) { .row { grid-template-columns: 1fr; } }
    .actions { display: flex; gap: 0.5rem; justify-content: flex-end; align-items: center; }
  `,
  template: `
    <header class="page-head"><div><h1>Website content</h1><p class="muted">What visitors see on the WaitLess website. Saved changes show within a minute.</p></div></header>
    @if (error(); as e) { <wl-error-state [message]="e.message" (retry)="load()" /> }
    @else if (!content()) { <wl-loading-state /> }
    @else {
      <div class="layout">
        <nav aria-label="Sections">
          @for (s of sections; track s.key) {
            <button type="button" [attr.aria-current]="key() === s.key" (click)="pick(s.key)" [attr.data-testid]="'section-' + s.key">{{ s.label }}</button>
          }
        </nav>
        <section class="panel">
          <h2>{{ current().label }}</h2>
          <form (ngSubmit)="save()">
            @for (f of fields(); track f.key) {
              @switch (f.kind) {
                @case ('text') {
                  <label class="field"><span>{{ nice(f.key) }}</span><input [name]="f.key" [(ngModel)]="f.value" [attr.data-testid]="'content-' + f.key" /></label>
                }
                @case ('long') {
                  <label class="field"><span>{{ nice(f.key) }}</span><textarea [name]="f.key" [(ngModel)]="f.value" rows="6" [attr.data-testid]="'content-' + f.key"></textarea></label>
                }
                @case ('list') {
                  <label class="field"><span>{{ nice(f.key) }} (one per line)</span><textarea [name]="f.key" [(ngModel)]="f.value" rows="5"></textarea></label>
                }
                @case ('rows') {
                  <fieldset class="field"><legend>{{ nice(f.key) }}</legend>
                    @for (r of f.value; track $index; let i = $index) {
                      <div class="row">
                        @for (c of f.cols; track c) {
                          <label class="field"><span>{{ nice(c) }}</span><input [name]="f.key + i + c" [(ngModel)]="r[c]" /></label>
                        }
                        <button mat-icon-button type="button" (click)="f.value.splice(i, 1)" aria-label="Remove"><mat-icon>delete</mat-icon></button>
                      </div>
                    }
                    <button mat-button type="button" (click)="addRow(f)"><mat-icon>add</mat-icon>Add</button>
                  </fieldset>
                }
              }
            }
            <div class="actions">
              <a [href]="current().page" target="_blank" rel="noopener" class="muted">Open the page ↗</a>
              <button mat-flat-button type="submit" [disabled]="busy()" data-testid="save-content">Save</button>
            </div>
          </form>
        </section>
      </div>
    }
  `,
})
export class SaContentPage implements OnInit {
  private readonly api = inject(SuperAdminService);
  private readonly snack = inject(MatSnackBar);
  protected readonly sections = SECTIONS;
  protected readonly content = signal<ContentMap | null>(null);
  protected readonly key = signal('home');
  protected readonly fields = signal<Field[]>([]);
  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly current = computed(() => SECTIONS.find((s) => s.key === this.key())!);

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.api.content().subscribe({
      next: (c) => {
        this.content.set(c);
        this.pick(this.key());
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }

  protected nice(k: string): string {
    return (k.charAt(0).toUpperCase() + k.slice(1)).replace(/_/g, ' ');
  }

  protected pick(key: string): void {
    this.key.set(key);
    const data = this.content()?.[key] ?? {};
    this.fields.set(
      Object.entries(data).map(([k, v]): Field => {
        if (Array.isArray(v) && v.length && typeof v[0] === 'object') {
          return { key: k, kind: 'rows', value: (v as Record<string, string>[]).map((r) => ({ ...r })), cols: Object.keys(v[0] as object) };
        }
        if (Array.isArray(v)) return { key: k, kind: 'list', value: (v as string[]).join('\n') };
        return { key: k, kind: LONG.has(k) || String(v).length > 120 ? 'long' : 'text', value: String(v ?? '') };
      }),
    );
  }

  protected addRow(f: Field): void {
    if (f.kind === 'rows') f.value.push(Object.fromEntries(f.cols.map((c) => [c, ''])));
  }

  protected save(): void {
    const body: Record<string, unknown> = {};
    for (const f of this.fields()) {
      if (f.kind === 'rows') body[f.key] = f.value.filter((r) => Object.values(r).some((x) => String(x).trim()));
      else if (f.kind === 'list') body[f.key] = f.value.split('\n').map((x) => x.trim()).filter(Boolean);
      else body[f.key] = f.value;
    }
    this.busy.set(true);
    this.api.saveContent(this.key(), body).subscribe({
      next: (saved) => {
        this.busy.set(false);
        this.content.set({ ...this.content()!, [this.key()]: saved });
        this.snack.open('Saved — the website shows it within a minute.', undefined, { duration: 3000 });
      },
      error: (e: ApiError) => {
        this.busy.set(false);
        this.snack.open(e.message, 'OK', { duration: 5000 });
      },
    });
  }
}

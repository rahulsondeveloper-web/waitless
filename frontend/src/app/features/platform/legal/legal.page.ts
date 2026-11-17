import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { map } from 'rxjs';

import { SiteContentService } from '../../../core/platform-admin/site-content.service';

/** Terms of use and privacy policy — text from Super Admin → Content (route data `section`). */
@Component({
  selector: 'wl-legal-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-page wl-container legal">
      @if (doc(); as d) {
        <h1 class="wl-h2">{{ d.title }}</h1>
        @if (d.updated) { <p class="muted">Last updated {{ d.updated }}</p> }
        @for (p of paragraphs(); track $index) { <p>{{ p }}</p> }
      } @else {
        <p class="muted">Loading…</p>
      }
    </section>
  `,
  styles: `
    .legal { max-width: 760px; }
    .legal p { line-height: 1.65; margin: 0 0 1rem; }
    .muted { color: var(--wl-text-soft); }
  `,
})
export class LegalPage {
  private readonly site = inject(SiteContentService);
  private readonly section = toSignal(inject(ActivatedRoute).data.pipe(map((d) => d['section'] as 'terms' | 'privacy')), {
    initialValue: 'terms' as const,
  });
  protected readonly doc = computed(() => this.site.content()?.[this.section()] ?? null);
  protected readonly paragraphs = computed(() => (this.doc()?.body ?? '').split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean));

  constructor() {
    this.site.load();
  }
}

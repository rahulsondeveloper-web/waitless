import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { map } from 'rxjs';

import { EmptyStateComponent } from '../state/state.components';

/**
 * Temporary page for routes whose feature is built in a later phase.
 * Route data: { title: string, phase: number }.
 */
@Component({
  selector: 'wl-placeholder-page',
  imports: [EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-page">
      <wl-empty-state
        icon="construction"
        [title]="data().title"
        [message]="'This section is built in Phase ' + data().phase + ' of the development plan.'"
      />
    </section>
  `,
})
export class PlaceholderPageComponent {
  private readonly route = inject(ActivatedRoute);
  protected readonly data = toSignal(
    this.route.data.pipe(map((d) => ({ title: (d['title'] as string) ?? 'Coming soon', phase: (d['phase'] as number) ?? 0 }))),
    { initialValue: { title: '', phase: 0 } },
  );
}

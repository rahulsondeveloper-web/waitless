import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { EmptyStateComponent } from '../../shared/ui/state/state.components';

@Component({
  selector: 'wl-not-found-page',
  imports: [RouterLink, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-page wl-container">
      <wl-empty-state icon="explore_off" title="Page not found" message="The page you are looking for does not exist.">
        <a routerLink="/" class="wl-btn wl-btn--primary">Back to WaitLess</a>
      </wl-empty-state>
    </section>
  `,
})
export class NotFoundPage {}

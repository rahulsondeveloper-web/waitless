import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

/** Loading, empty and error states (PRD §29 rule 12). Theme-aware via --wl-* variables. */

@Component({
  selector: 'wl-loading-state',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wl-state" role="status" aria-live="polite">
      <span class="wl-spinner" aria-hidden="true"></span>
      <p>{{ label() }}</p>
    </div>
  `,
})
export class LoadingStateComponent {
  readonly label = input('Loading…');
}

@Component({
  selector: 'wl-empty-state',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wl-state">
      <span class="material-symbols-outlined wl-state__icon" aria-hidden="true">{{ icon() }}</span>
      <h3>{{ title() }}</h3>
      @if (message()) {
        <p>{{ message() }}</p>
      }
      <ng-content />
    </div>
  `,
})
export class EmptyStateComponent {
  readonly title = input.required<string>();
  readonly message = input<string>();
  readonly icon = input('inbox');
}

@Component({
  selector: 'wl-error-state',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wl-state wl-state--error" role="alert">
      <span class="material-symbols-outlined wl-state__icon" aria-hidden="true">error</span>
      <h3>{{ title() }}</h3>
      <p>{{ message() }}</p>
      @if (retryable()) {
        <button type="button" class="wl-btn wl-btn--ghost" (click)="retry.emit()">Try again</button>
      }
    </div>
  `,
})
export class ErrorStateComponent {
  readonly title = input('Something went wrong');
  readonly message = input('Please try again.');
  readonly retryable = input(true);
  readonly retry = output<void>();
}

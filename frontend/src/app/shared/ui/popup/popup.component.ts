import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, HostListener, OnDestroy, inject, input, output } from '@angular/core';

/**
 * A centred pop-up over a dimmed page (storefront). Closes on the backdrop, the × button and Escape;
 * focus moves into it and returns to the button that opened it.
 */
@Component({
  selector: 'wl-popup',
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .backdrop { position: fixed; inset: 0; z-index: 60; background: rgb(0 0 0 / 45%); }
    .popup { position: fixed; z-index: 61; left: 50%; top: 50%; transform: translate(-50%, -50%);
      width: min(var(--popup-width, 520px), calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto;
      background: var(--wl-surface, #fff); color: var(--wl-text); border-radius: 16px; padding: 1.2rem;
      box-shadow: 0 20px 50px rgb(0 0 0 / 25%); display: grid; gap: 0.75rem; text-align: left; }
    .head { display: flex; align-items: start; justify-content: space-between; gap: 1rem; }
    h2 { margin: 0; font: 600 1.5rem var(--wl-font-serif); }
    .x { border: 0; background: transparent; color: inherit; cursor: pointer; padding: 0.2rem; border-radius: 8px; line-height: 0; }
    .x:hover { background: var(--wl-surface-alt, #f3ede7); }
  `,
  template: `
    <div class="backdrop" (click)="closed.emit()" aria-hidden="true"></div>
    <div class="popup" role="dialog" aria-modal="true" [attr.aria-label]="title()" tabindex="-1" [attr.data-testid]="testId()">
      <div class="head">
        <h2>{{ title() }}</h2>
        <button type="button" class="x" (click)="closed.emit()" aria-label="Close">
          <span class="material-symbols-outlined" aria-hidden="true">close</span>
        </button>
      </div>
      <ng-content />
    </div>
  `,
})
export class PopupComponent implements AfterViewInit, OnDestroy {
  readonly title = input.required<string>();
  readonly testId = input<string | null>(null);
  readonly closed = output<void>();
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly opener = document.activeElement as HTMLElement | null;

  ngAfterViewInit(): void {
    this.host.nativeElement.querySelector<HTMLElement>('.popup')?.focus();
  }

  ngOnDestroy(): void {
    this.opener?.focus?.();
  }

  @HostListener('document:keydown.escape')
  protected escape(): void {
    this.closed.emit();
  }
}

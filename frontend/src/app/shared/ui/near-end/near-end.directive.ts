import { DestroyRef, Directive, ElementRef, effect, inject, input, output } from '@angular/core';

/**
 * "Load more on scroll": put it on every list row and give the row that should trigger the next
 * batch a key (e.g. its category ID); all other rows get null. When that row comes into view
 * (with a margin, so the next batch is usually there before the guest reaches the end),
 * `wlNearEnd` emits the key once.
 */
@Directive({ selector: '[wlNearEndKey]' })
export class NearEndDirective {
  readonly key = input<string | null | undefined>(null, { alias: 'wlNearEndKey' });
  readonly nearEnd = output<string>({ alias: 'wlNearEnd' });

  private readonly el = inject<ElementRef<HTMLElement>>(ElementRef);
  private observer: IntersectionObserver | null = null;

  constructor() {
    effect(() => {
      const key = this.key();
      this.stop();
      if (!key) return;
      if (typeof IntersectionObserver === 'undefined') {
        this.nearEnd.emit(key); // very old browser: just load the next batch
        return;
      }
      this.observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            this.stop();
            this.nearEnd.emit(key);
          }
        },
        { rootMargin: '0px 0px 300px 0px' },
      );
      this.observer.observe(this.el.nativeElement);
    });
    inject(DestroyRef).onDestroy(() => this.stop());
  }

  private stop(): void {
    this.observer?.disconnect();
    this.observer = null;
  }
}

import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  computed,
  input,
  model,
  viewChild,
} from '@angular/core';

export interface LightboxImage {
  url: string;
  caption?: string;
  width?: number;
  height?: number;
}

/**
 * Full-screen image viewer (PRD §5.3 "image enlargement, next/previous").
 * Keyboard: ← → to move, Esc to close. Swipe on touch screens. Focus is trapped and restored.
 */
@Component({
  selector: 'wl-lightbox',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(document:keydown)': 'onKey($event)',
  },
  template: `
    <div
      #dialog
      class="lb"
      role="dialog"
      aria-modal="true"
      [attr.aria-label]="'Photo ' + (index()! + 1) + ' of ' + images().length"
      tabindex="-1"
      (click)="close()"
      (touchstart)="touchStart($event)"
      (touchend)="touchEnd($event)"
    >
      <figure (click)="$event.stopPropagation()">
        <img [src]="current()?.url" [alt]="current()?.caption || 'Photo ' + (index()! + 1)" />
        <figcaption>
          <span>{{ current()?.caption }}</span>
          <span class="count">{{ index()! + 1 }} / {{ images().length }}</span>
        </figcaption>
      </figure>
      @if (images().length > 1) {
        <button type="button" class="nav prev" (click)="step(-1, $event)" aria-label="Previous photo">
          <span class="material-symbols-outlined">chevron_left</span>
        </button>
        <button type="button" class="nav next" (click)="step(1, $event)" aria-label="Next photo">
          <span class="material-symbols-outlined">chevron_right</span>
        </button>
      }
      <button type="button" class="close" (click)="close()" aria-label="Close">
        <span class="material-symbols-outlined">close</span>
      </button>
    </div>
  `,
  styleUrl: './lightbox.component.scss',
})
export class LightboxComponent implements AfterViewInit, OnDestroy {
  readonly images = input.required<LightboxImage[]>();
  /** Index of the open image; set to null to close. Two-way bindable: [(index)]. */
  readonly index = model<number | null>(null);

  protected readonly current = computed(() => {
    const i = this.index();
    return i === null ? null : this.images()[i];
  });
  private readonly dialog = viewChild.required<ElementRef<HTMLElement>>('dialog');
  private readonly opener = document.activeElement as HTMLElement | null;
  private touchX: number | null = null;

  ngAfterViewInit(): void {
    this.dialog().nativeElement.focus();
    document.body.style.overflow = 'hidden';
  }

  ngOnDestroy(): void {
    document.body.style.overflow = '';
    this.opener?.focus?.();
  }

  protected step(delta: number, event?: Event): void {
    event?.stopPropagation();
    const n = this.images().length;
    this.index.update((i) => (i === null ? null : (i + delta + n) % n));
  }

  protected close(): void {
    this.index.set(null);
  }

  protected onKey(e: KeyboardEvent): void {
    if (e.key === 'Escape') this.close();
    else if (e.key === 'ArrowRight') this.step(1);
    else if (e.key === 'ArrowLeft') this.step(-1);
    else if (e.key === 'Tab') {
      // keep focus inside the dialog
      const focusable = Array.from(this.dialog().nativeElement.querySelectorAll<HTMLElement>('button'));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        last.focus();
        e.preventDefault();
      } else if (!e.shiftKey && document.activeElement === last) {
        first.focus();
        e.preventDefault();
      }
    }
  }

  protected touchStart(e: TouchEvent): void {
    this.touchX = e.changedTouches[0]?.clientX ?? null;
  }

  protected touchEnd(e: TouchEvent): void {
    if (this.touchX === null) return;
    const dx = (e.changedTouches[0]?.clientX ?? this.touchX) - this.touchX;
    this.touchX = null;
    if (Math.abs(dx) > 50) this.step(dx < 0 ? 1 : -1);
  }
}

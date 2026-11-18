import { ChangeDetectionStrategy, Component, ElementRef, HostListener, effect, inject, signal, untracked } from '@angular/core';

import { CartService } from '../../../core/ordering/cart.service';
import { GuestServiceApi, GuestWifi } from '../../../core/ordering/guest-service.service';

/** "Restaurant Wi-Fi" for guests whose phone has joined a table: a small pop-up with name + password. */
@Component({
  selector: 'wl-wifi-button',
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    :host { position: relative; display: inline-flex; }
    .tip { position: absolute; top: calc(100% + 10px); left: 50%; transform: translateX(-50%); z-index: 30; min-width: 230px;
      padding: 0.8rem 0.9rem; border-radius: 12px; background: var(--wl-text, #2b2522); color: #fff; text-align: left;
      box-shadow: var(--wl-shadow); display: grid; gap: 0.35rem; }
    .tip::before { content: ''; position: absolute; top: -6px; left: 50%; width: 12px; height: 12px; background: inherit;
      transform: translateX(-50%) rotate(45deg); }
    .tip small { opacity: 0.75; font-size: 0.75rem; }
    .tip b { font: 600 1rem ui-monospace, monospace; word-break: break-all; user-select: all; }
    .copy { justify-self: start; margin-top: 0.2rem; padding: 0.25rem 0.6rem; border: 1px solid rgba(255, 255, 255, 0.5);
      border-radius: 8px; background: transparent; color: #fff; font: 600 0.8rem var(--wl-font-sans); cursor: pointer; }
  `,
  template: `
    @if (wifi(); as w) {
      <button type="button" class="wl-btn wl-btn--light" (click)="open.set(!open())" [attr.aria-expanded]="open()"
              aria-haspopup="dialog" data-testid="wifi-button">
        <span class="material-symbols-outlined" aria-hidden="true">wifi</span> Restaurant Wi-Fi
      </button>
      @if (open()) {
        <div class="tip" role="dialog" aria-label="Restaurant Wi-Fi" data-testid="wifi-tip">
          @if (w.name) { <small>Network</small><b data-testid="wifi-tip-name">{{ w.name }}</b> }
          @if (w.password) { <small>Password</small><b data-testid="wifi-tip-password">{{ w.password }}</b> }
          @if (w.password) {
            <button type="button" class="copy" (click)="copy(w.password)">{{ copied() ? 'Copied ✓' : 'Copy password' }}</button>
          }
        </div>
      }
    }
  `,
})
export class WifiButtonComponent {
  private readonly api = inject(GuestServiceApi);
  private readonly cart = inject(CartService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  protected readonly wifi = signal<GuestWifi | null>(null);
  protected readonly open = signal(false);
  protected readonly copied = signal(false);

  constructor() {
    effect(() => {
      const token = this.cart.tableToken();
      untracked(() => {
        this.wifi.set(null);
        this.open.set(false);
        if (token) this.api.wifi(token).subscribe({ next: (w) => this.wifi.set(w), error: () => this.wifi.set(null) });
      });
    });
  }

  @HostListener('document:click', ['$event'])
  protected outside(e: MouseEvent): void {
    if (this.open() && !this.host.nativeElement.contains(e.target as Node)) this.open.set(false);
  }

  @HostListener('document:keydown.escape')
  protected escape(): void {
    this.open.set(false);
  }

  protected copy(text: string): void {
    void navigator.clipboard?.writeText(text).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1800);
    });
  }
}

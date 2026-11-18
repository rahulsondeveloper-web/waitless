import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal, effect, untracked } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { ApiError } from '../../../core/http/api-error';
import { Gallery } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { LightboxComponent, LightboxImage } from '../../../shared/ui/lightbox/lightbox.component';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Restaurant gallery (PRD §5.3, §6): up to 5 photos, enlarge with next/previous. */
@Component({
  selector: 'wl-storefront-gallery',
  imports: [LightboxComponent, LoadingStateComponent, ErrorStateComponent, EmptyStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="wl-container page">
      <header class="head">
        <p class="eyebrow">Gallery</p>
        <h1 class="title">A look <span class="script">inside</span> {{ ctx.restaurant()?.name }}</h1>
      </header>
      @if (error(); as e) {
        <wl-error-state title="Could not load photos" [message]="e.message" (retry)="load()" />
      } @else if (!gallery()) {
        <wl-loading-state />
      } @else if (!images().length) {
        <wl-empty-state icon="photo_library" title="No photos yet" />
      } @else {
        <ul class="grid" [class]="'grid grid--' + images().length">
          @for (img of images(); track img.url; let i = $index) {
            <li>
              <button type="button" (click)="open.set(i)" [attr.aria-label]="'Enlarge photo ' + (i + 1) + (img.caption ? ': ' + img.caption : '')">
                <img [src]="img.url" [alt]="img.caption || 'Photo ' + (i + 1)" loading="lazy" />
                @if (img.caption) { <span class="cap">{{ img.caption }}</span> }
              </button>
            </li>
          }
        </ul>
      }
    </section>
    @if (open() !== null) {
      <wl-lightbox [images]="images()" [(index)]="open" />
    }
  `,
  styles: `
    .page {
      padding-block: 2.5rem;
    }
    .head {
      text-align: center;
      margin-bottom: 1.6rem;
    }
    .eyebrow {
      font-size: 0.78rem;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--wl-primary);
    }
    .title {
      font: 600 clamp(2rem, 4vw, 3rem) / 1.1 var(--wl-font-serif);
    }
    .script {
      font-family: var(--wl-font-script);
      font-weight: 400;
      color: var(--wl-primary);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 0.8rem;
    }
    /* first two photos large, the rest smaller */
    li {
      grid-column: span 2;
    }
    li:nth-child(-n + 2) {
      grid-column: span 3;
    }
    .grid--1 li,
    .grid--3 li:first-child {
      grid-column: 1 / -1;
    }
    .grid--3 li:nth-child(2),
    .grid--3 li:nth-child(3) {
      grid-column: span 3;
    }
    button {
      position: relative;
      display: block;
      width: 100%;
      padding: 0;
      border: 0;
      border-radius: var(--wl-radius);
      overflow: hidden;
      background: var(--wl-surface-alt);
      cursor: zoom-in;
    }
    img {
      display: block;
      width: 100%;
      aspect-ratio: 4 / 3;
      object-fit: cover;
      transition: transform 0.35s;
    }
    button:hover img {
      transform: scale(1.03);
    }
    .cap {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      padding: 1.4rem 0.8rem 0.6rem;
      background: linear-gradient(to top, rgba(0, 0, 0, 0.65), transparent);
      color: #fff;
      font-size: 0.85rem;
      text-align: left;
    }
    @media (max-width: 640px) {
      .grid li {
        grid-column: 1 / -1 !important;
      }
    }
  `,
})
export class StorefrontGalleryPage implements OnInit {
  protected readonly ctx = inject(TenantContextService);
  private readonly route = inject(ActivatedRoute);
  protected readonly gallery = signal<Gallery | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly open = signal<number | null>(null);
  protected readonly images = computed<LightboxImage[]>(
    () => this.gallery()?.items.map((i) => ({ url: i.url, caption: i.caption, width: i.width, height: i.height })) ?? [],
  );

  constructor() {
    // The restaurant changed its photos (server push): reload without the spinner.
    let seen = this.ctx.version();
    effect(() => {
      const v = this.ctx.version();
      if (v === seen) return;
      seen = v;
      untracked(() => this.load());
    });
  }

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.error.set(null);
    this.ctx.gallery().subscribe({
      next: (g) => {
        this.gallery.set(g);
        const start = Number(this.route.snapshot.queryParamMap.get('photo'));
        if (Number.isInteger(start) && this.route.snapshot.queryParamMap.has('photo') && g.items[start]) {
          this.open.set(start); // deep link from the homepage strip
        }
      },
      error: (e: ApiError) => this.error.set(e),
    });
  }
}

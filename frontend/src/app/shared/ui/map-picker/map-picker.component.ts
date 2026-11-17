import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import type * as Leaflet from 'leaflet';

import { ApiError } from '../../../core/http/api-error';
import { ApiService } from '../../../core/http/api.service';
import { OSM_ATTRIBUTION, OSM_TILES, loadLeaflet, pinIcon } from '../map/leaflet-loader';

export interface Place extends LatLng {
  label: string;
  city: string | null;
  state: string | null;
  postal_code: string | null;
}

export interface LatLng {
  lat: number;
  lng: number;
}

const INDIA: LatLng = { lat: 20.5937, lng: 78.9629 };

/**
 * Find an address (server-side geocoding: Nominatim, or Google when configured — decision D25), then click
 * or drag the pin to the exact entrance. Leaflet is loaded lazily so it never weighs on pages without a map.
 */
@Component({
  selector: 'wl-map-picker',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (searchable()) {
      <!-- not a <form>: the picker usually sits inside the page's own form -->
      <div class="find" role="search">
        <input #q type="search" placeholder="Search the address, e.g. 12 Olive Street, Koregaon Park, Pune" aria-label="Search the address"
               (keydown.enter)="$event.preventDefault(); find(q.value)" data-testid="map-search" />
        <button type="button" class="find__btn" (click)="find(q.value)" [disabled]="searching()" data-testid="map-find">
          {{ searching() ? 'Searching…' : 'Find' }}</button>
      </div>
      @if (searchError(); as e) { <p class="map-note err" role="alert">{{ e }}</p> }
      @if (results().length) {
        <ul class="results" data-testid="map-results">
          @for (r of results(); track $index) {
            <li><button type="button" (click)="choose(r)">{{ r.label }}</button></li>
          }
        </ul>
      }
    }
    <div #map class="map" role="application" aria-label="Map: click to place your restaurant's pin"></div>
    @if (failed()) {
      <p class="map-note">The map could not load. You can still enter the coordinates manually.</p>
    } @else {
      <p class="map-note">Click the map or drag the pin to your entrance. Map data © OpenStreetMap contributors.</p>
    }
  `,
  styles: `
    .map {
      height: 320px;
      border-radius: 12px;
      border: 1px solid var(--wl-line);
      z-index: 0;
    }
    .map-note {
      font-size: 0.78rem;
      color: var(--wl-muted);
      margin-top: 0.4rem;
    }
    .err { color: #a3321c; }
    .find { display: flex; gap: 0.4rem; margin-bottom: 0.5rem; }
    .find input { flex: 1; font: inherit; padding: 0.45rem 0.6rem; border: 1px solid var(--wl-line); border-radius: 8px; min-height: 38px; }
    .find__btn { font: inherit; padding: 0 1rem; border-radius: 8px; border: 1px solid var(--wl-primary); background: var(--wl-primary); color: #fff; cursor: pointer; }
    .results { list-style: none; margin: 0 0 0.5rem; padding: 0; border: 1px solid var(--wl-line); border-radius: 8px; overflow: hidden; }
    .results button { width: 100%; text-align: left; font: inherit; font-size: 0.88rem; padding: 0.45rem 0.6rem; background: var(--wl-surface, #fff); border: 0; border-bottom: 1px solid var(--wl-line); cursor: pointer; color: var(--wl-text); }
    .results button:hover, .results button:focus { background: color-mix(in srgb, var(--wl-primary) 8%, transparent); }
  `,
})
export class MapPickerComponent implements AfterViewInit, OnDestroy {
  readonly value = input<LatLng | null>(null);
  readonly searchable = input(true);
  readonly picked = output<LatLng>();
  /** The chosen search result (city, state, PIN code) — pages may use it to fill the address form. */
  readonly found = output<Place>();

  private readonly api = inject(ApiService);
  protected readonly searching = signal(false);
  protected readonly searchError = signal<string | null>(null);
  protected readonly results = signal<Place[]>([]);

  protected readonly failed = signal(false);
  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('map');
  private L?: typeof Leaflet;
  private map?: Leaflet.Map;
  private marker?: Leaflet.Marker;

  constructor() {
    // Keep the pin in sync when the value changes from outside (e.g. typed coordinates).
    effect(() => {
      const v = this.value();
      if (v && this.map) this.place(v, false);
    });
  }

  async ngAfterViewInit(): Promise<void> {
    try {
      this.L = await loadLeaflet();
    } catch {
      this.failed.set(true);
      return;
    }
    const L = this.L;
    const start = this.value();
    this.map = L.map(this.host().nativeElement, { scrollWheelZoom: false }).setView(
      start ?? INDIA,
      start ? 16 : 5,
    );
    L.tileLayer(OSM_TILES, { maxZoom: 19, attribution: OSM_ATTRIBUTION }).addTo(this.map);
    this.map.on('click', (e: Leaflet.LeafletMouseEvent) => this.place(e.latlng, true));
    if (start) this.place(start, false);
  }

  ngOnDestroy(): void {
    this.map?.remove();
  }

  protected find(q: string): void {
    if (q.trim().length < 3) return;
    this.searching.set(true);
    this.searchError.set(null);
    this.api.get<Place[]>('restaurant/geocode', { q: q.trim() }).subscribe({
      next: (r) => {
        this.searching.set(false);
        this.results.set(r);
        if (!r.length) this.searchError.set('No match — try fewer words, or drop the pin on the map.');
      },
      error: (e: ApiError) => {
        this.searching.set(false);
        this.searchError.set(e.message);
      },
    });
  }

  protected choose(p: Place): void {
    this.results.set([]);
    if (this.map) {
      this.place(p, true);
      this.map.setView(p, 17);
    } else {
      this.picked.emit(round(p));
    }
    this.found.emit(p);
  }

  private place(p: LatLng, emit: boolean): void {
    const L = this.L!;
    if (!this.marker) {
      const icon = pinIcon(L);
      this.marker = L.marker(p, { draggable: true, icon, keyboard: true, title: 'Restaurant location' }).addTo(this.map!);
      this.marker.on('dragend', () => this.picked.emit(round(this.marker!.getLatLng())));
    } else {
      this.marker.setLatLng(p);
    }
    if (emit) {
      this.picked.emit(round(p));
    } else {
      this.map!.setView(p, Math.max(this.map!.getZoom(), 15));
    }
  }
}

function round(p: LatLng): LatLng {
  return { lat: Math.round(p.lat * 1e6) / 1e6, lng: Math.round(p.lng * 1e6) / 1e6 };
}

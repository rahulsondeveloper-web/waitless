import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import type * as Leaflet from 'leaflet';

import { OSM_ATTRIBUTION, OSM_TILES, loadLeaflet, pinIcon } from '../map/leaflet-loader';

export interface LatLng {
  lat: number;
  lng: number;
}

const INDIA: LatLng = { lat: 20.5937, lng: 78.9629 };

/**
 * Click (or drag the pin) to set a location. OpenStreetMap tiles for now (decision D25);
 * Leaflet is loaded lazily so it never weighs on pages without a map.
 */
@Component({
  selector: 'wl-map-picker',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
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
  `,
})
export class MapPickerComponent implements AfterViewInit, OnDestroy {
  readonly value = input<LatLng | null>(null);
  readonly picked = output<LatLng>();

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

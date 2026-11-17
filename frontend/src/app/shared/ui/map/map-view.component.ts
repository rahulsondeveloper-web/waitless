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

import { OSM_ATTRIBUTION, OSM_TILES, loadLeaflet, pinIcon } from './leaflet-loader';

export interface MapMarker {
  id: string;
  lat: number;
  lng: number;
  title: string;
  subtitle?: string;
  link?: string; // in-app URL shown in the popup
}

/** Read-only map with markers (contact page, discovery). Fits all markers in view. */
@Component({
  selector: 'wl-map-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #map class="map" role="region" [attr.aria-label]="label()"></div>
    @if (failed()) {
      <p class="note">The map could not load.</p>
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .map {
      height: var(--map-height, 320px);
      border-radius: 14px;
      border: 1px solid var(--wl-line);
      z-index: 0;
    }
    .note {
      font-size: 0.8rem;
      color: var(--wl-muted);
    }
  `,
})
export class MapViewComponent implements AfterViewInit, OnDestroy {
  readonly markers = input<MapMarker[]>([]);
  readonly highlight = input<string | null>(null);
  readonly label = input('Map');
  readonly selected = output<string>();

  protected readonly failed = signal(false);
  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('map');
  private L?: typeof Leaflet;
  private map?: Leaflet.Map;
  private layer?: Leaflet.LayerGroup;

  constructor() {
    effect(() => {
      const markers = this.markers();
      const hi = this.highlight();
      if (this.map) this.draw(markers, hi);
    });
  }

  async ngAfterViewInit(): Promise<void> {
    try {
      this.L = await loadLeaflet();
    } catch {
      this.failed.set(true);
      return;
    }
    this.map = this.L.map(this.host().nativeElement, { scrollWheelZoom: false }).setView([20.59, 78.96], 5);
    this.L.tileLayer(OSM_TILES, { maxZoom: 19, attribution: OSM_ATTRIBUTION }).addTo(this.map);
    this.layer = this.L.layerGroup().addTo(this.map);
    this.draw(this.markers(), this.highlight());
  }

  ngOnDestroy(): void {
    this.map?.remove();
  }

  private draw(markers: MapMarker[], hi: string | null): void {
    const L = this.L!;
    this.layer!.clearLayers();
    const points: Leaflet.LatLngExpression[] = [];
    for (const m of markers) {
      const marker = L.marker([m.lat, m.lng], { icon: pinIcon(L, m.id === hi), title: m.title, keyboard: true });
      const popup = document.createElement('div');
      const title = document.createElement(m.link ? 'a' : 'b');
      title.textContent = m.title; // textContent: no HTML injection from restaurant names
      if (m.link) (title as HTMLAnchorElement).href = m.link;
      popup.appendChild(title);
      if (m.subtitle) {
        const sub = document.createElement('div');
        sub.textContent = m.subtitle;
        popup.appendChild(sub);
      }
      marker.bindPopup(popup);
      marker.on('click', () => this.selected.emit(m.id));
      marker.addTo(this.layer!);
      points.push([m.lat, m.lng]);
    }
    if (points.length === 1) this.map!.setView(points[0], 15);
    else if (points.length > 1) this.map!.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 14 });
  }
}

import type * as Leaflet from 'leaflet';

let loading: Promise<typeof Leaflet> | null = null;

/**
 * Lazily loads Leaflet and its stylesheet (built as a separate, non-injected bundle in angular.json),
 * so pages without a map never pay for it. OpenStreetMap tiles for now (decision D25).
 */
export function loadLeaflet(): Promise<typeof Leaflet> {
  if (!document.querySelector('link[data-leaflet]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'leaflet.css';
    link.dataset['leaflet'] = '';
    document.head.appendChild(link);
  }
  loading ??= import('leaflet');
  return loading;
}

export const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
export const OSM_ATTRIBUTION = '&copy; OpenStreetMap contributors';

/** Pin without image assets (styled by .wl-pin in global styles). */
export function pinIcon(L: typeof Leaflet, highlighted = false): Leaflet.DivIcon {
  return L.divIcon({
    className: highlighted ? 'wl-pin wl-pin--hi' : 'wl-pin',
    html: '<span></span>',
    iconSize: [28, 28],
    iconAnchor: [14, 28],
    popupAnchor: [0, -26],
  });
}

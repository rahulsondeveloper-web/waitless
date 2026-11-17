import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';

import { WEEKDAYS } from '../../../core/restaurant/restaurant.models';
import { PublicBranch, SOCIAL_LABELS } from '../../../core/storefront/storefront.models';
import { TenantContextService } from '../../../core/storefront/tenant-context.service';
import { MapMarker, MapViewComponent } from '../../../shared/ui/map/map-view.component';

/** Restaurant Contact (PRD §6): address, phone, email, map, opening hours, social links. */
@Component({
  selector: 'wl-storefront-contact',
  imports: [MapViewComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './contact.page.html',
  styleUrl: './contact.page.scss',
})
export class StorefrontContactPage {
  protected readonly ctx = inject(TenantContextService);
  protected readonly weekdays = WEEKDAYS;
  protected readonly socialLabels = SOCIAL_LABELS;
  protected readonly todayIndex = (new Date().getDay() + 6) % 7; // JS Sunday=0 → Monday=0

  protected readonly markers = computed<MapMarker[]>(() =>
    (this.ctx.restaurant()?.branches ?? [])
      .filter((b) => b.lat && b.lng)
      .map((b) => ({ id: b.id, lat: +b.lat!, lng: +b.lng!, title: b.name, subtitle: `${b.address_line}, ${b.city}` })),
  );

  protected hoursText(b: PublicBranch, weekday: number): string {
    const d = b.hours.find((h) => h.weekday === weekday);
    if (!d) return '—';
    if (d.is_closed || !d.opens_at || !d.closes_at) return 'Closed';
    return `${d.opens_at.slice(0, 5)} – ${d.closes_at.slice(0, 5)}`;
  }

  protected directions(b: PublicBranch): string {
    const q = b.lat && b.lng ? `${b.lat},${b.lng}` : `${b.address_line}, ${b.city}, ${b.state}`;
    return `https://www.openstreetmap.org/directions?to=${encodeURIComponent(q)}`;
  }
}

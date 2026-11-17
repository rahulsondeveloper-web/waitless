import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, of } from 'rxjs';

import { TenantContextService } from '../../../core/storefront/tenant-context.service';

/** Restaurant homepage (PRD §6 Home). */
@Component({
  selector: 'wl-storefront-home',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './home.page.html',
  styleUrl: './home.page.scss',
})
export class StorefrontHomePage {
  protected readonly ctx = inject(TenantContextService);
  protected readonly r = this.ctx.restaurant;
  protected readonly branch = this.ctx.primaryBranch;
  protected readonly gallery = toSignal(this.ctx.gallery().pipe(catchError(() => of(null))), { initialValue: null });
  protected readonly photos = computed(() => this.gallery()?.items.slice(0, 3) ?? []);
  protected readonly mapsUrl = computed(() => {
    const b = this.branch();
    if (!b) return null;
    const q = b.lat && b.lng ? `${b.lat},${b.lng}` : `${b.address_line}, ${b.city}`;
    return `https://www.openstreetmap.org/search?query=${encodeURIComponent(q)}`;
  });
}

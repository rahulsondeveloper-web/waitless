import { BreakpointObserver } from '@angular/cdk/layout';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';

import { UserMenuComponent } from '../../shared/ui/user-menu/user-menu.component';

export interface AdminNavItem {
  label: string;
  icon: string;
  path: string;
}

/**
 * Shared shell for Restaurant Admin and Super Admin dashboards (Angular Material).
 * Route data: { area: string, nav: AdminNavItem[] }.
 */
@Component({
  selector: 'wl-admin-layout',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatSidenavModule,
    MatToolbarModule,
    MatListModule,
    MatIconModule,
    MatButtonModule,
    UserMenuComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './admin-layout.component.html',
  styleUrl: './admin-layout.component.scss',
})
export class AdminLayoutComponent {
  private readonly data = toSignal(inject(ActivatedRoute).data, { initialValue: {} as Record<string, unknown> });
  protected readonly area = computed(() => (this.data()['area'] as string) ?? 'Admin');
  protected readonly nav = computed(() => (this.data()['nav'] as AdminNavItem[]) ?? []);
  protected readonly isHandset = toSignal(
    inject(BreakpointObserver)
      .observe('(max-width: 900px)')
      .pipe(map((r) => r.matches)),
    { initialValue: false },
  );
}

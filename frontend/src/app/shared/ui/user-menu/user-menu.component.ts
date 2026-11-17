import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';

/**
 * Header account control used by every layout.
 * Signed out: "Login / Register". Signed in: name + menu (dashboard, switch restaurant, sign out).
 */
@Component({
  selector: 'wl-user-menu',
  imports: [RouterLink, MatMenuModule, MatButtonModule, MatIconModule, MatDividerModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (auth.user(); as u) {
      <button type="button" class="um-trigger" [matMenuTriggerFor]="menu" [attr.aria-label]="'Account menu for ' + displayName()">
        <span class="um-avatar" aria-hidden="true">{{ initials() }}</span>
        @if (!compact()) {
          <span class="um-name">{{ displayName() }}</span>
        }
      </button>
      <mat-menu #menu="matMenu" xPosition="before">
        <div class="um-head" mat-menu-item disabled>
          <b>{{ displayName() }}</b>
          <small>{{ u.email || u.phone }}</small>
        </div>
        <mat-divider />
        @if (auth.isSuperAdmin()) {
          <a mat-menu-item routerLink="/super-admin"><mat-icon>admin_panel_settings</mat-icon>Super Admin</a>
        }
        @if (auth.activeTenant(); as t) {
          <a mat-menu-item routerLink="/restaurant-admin"><mat-icon>storefront</mat-icon>{{ t.tenant_name }}</a>
        }
        @for (m of otherMemberships(); track m.tenant_id) {
          <button mat-menu-item type="button" (click)="switchTo(m.tenant_id)">
            <mat-icon>swap_horiz</mat-icon>Switch to {{ m.tenant_name }}
          </button>
        }
        @if (!auth.isSuperAdmin() && !auth.activeTenant()) {
          <a mat-menu-item routerLink="/customer"><mat-icon>person</mat-icon>My account</a>
        }
        <mat-divider />
        <button mat-menu-item type="button" (click)="auth.logout()"><mat-icon>logout</mat-icon>Sign out</button>
      </mat-menu>
    } @else {
      <a routerLink="/login" class="wl-btn wl-btn--primary wl-btn--sm">Login / Register</a>
    }
  `,
  styles: `
    .um-trigger {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.25rem 0.7rem 0.25rem 0.25rem;
      border: 1px solid var(--wl-line);
      border-radius: 999px;
      background: var(--wl-surface);
      color: var(--wl-text);
      max-width: 220px;
    }
    .um-avatar {
      display: grid;
      place-items: center;
      width: 32px;
      height: 32px;
      flex: none;
      border-radius: 50%;
      background: var(--wl-primary);
      color: #fff;
      font-weight: 600;
      font-size: 0.8rem;
    }
    .um-name {
      font-size: 0.88rem;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .um-head {
      display: grid;
      line-height: 1.3;
      height: auto;
      padding-block: 0.6rem;
      opacity: 1;
      small {
        color: var(--wl-muted);
      }
    }
  `,
})
export class UserMenuComponent {
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly snack = inject(MatSnackBar);

  /** Avatar only (small headers). */
  readonly compact = input(false);

  protected readonly displayName = computed(() => {
    const u = this.auth.user();
    return u?.full_name || u?.email || u?.phone || 'Account';
  });
  protected readonly initials = computed(() =>
    this.displayName()
      .split(/[\s@]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0].toUpperCase())
      .join(''),
  );
  protected readonly otherMemberships = computed(() =>
    this.auth.memberships().filter((m) => m.tenant_id !== this.auth.activeTenant()?.tenant_id),
  );

  protected switchTo(tenantId: string): void {
    this.auth.switchTenant(tenantId).subscribe({
      next: () => void this.router.navigateByUrl('/restaurant-admin'),
      error: (e: ApiError) => this.snack.open(e.message, 'Dismiss', { duration: 4000 }),
    });
  }
}

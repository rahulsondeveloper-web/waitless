import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { APP_CONFIG } from '../../core/config/app-config';
import { ThemeService } from '../../core/theme/theme.service';
import { UserMenuComponent } from '../../shared/ui/user-menu/user-menu.component';

/** WaitLess public website: landing, about, discovery, auth, customer account. */
@Component({
  selector: 'wl-platform-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, UserMenuComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './platform-layout.component.html',
  styleUrl: './platform-layout.component.scss',
})
export class PlatformLayoutComponent {
  protected readonly config = APP_CONFIG;
  protected readonly menuOpen = signal(false);
  protected readonly year = new Date().getFullYear();

  protected readonly nav = [
    { label: 'Home', link: '/', fragment: undefined },
    { label: 'About Us', link: '/about', fragment: undefined },
    { label: 'How It Works', link: '/', fragment: 'how-it-works' },
    { label: 'Features', link: '/', fragment: 'features' },
    { label: 'For Restaurants', link: '/', fragment: 'for-restaurants' },
    { label: 'Restaurants', link: '/restaurants', fragment: undefined },
    { label: 'Contact', link: '/', fragment: 'contact' },
  ];

  constructor() {
    // Entering the platform site always restores WaitLess branding (PRD §2.2).
    inject(ThemeService).reset();
  }

  protected toggleMenu(): void {
    this.menuOpen.update((v) => !v);
  }
}

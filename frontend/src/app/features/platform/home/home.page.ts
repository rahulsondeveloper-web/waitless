import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { APP_CONFIG } from '../../../core/config/app-config';

/**
 * WaitLess landing page. Phase 1 = structure and anchors used by the header;
 * Phase 4 fills it from the CMS content API (Super Admin editable, PRD §16).
 */
@Component({
  selector: 'wl-home-page',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './home.page.html',
  styleUrl: './home.page.scss',
})
export class HomePage {
  protected readonly config = APP_CONFIG;

  protected readonly steps = [
    { icon: 'search', title: 'Discover', text: 'Find restaurants near you and see live waiting times.' },
    { icon: 'event_available', title: 'Book or queue', text: 'Reserve a table or join the digital queue from your phone.' },
    { icon: 'restaurant_menu', title: 'Order', text: 'Browse the menu and order — even before you arrive with a paid booking.' },
    { icon: 'timer', title: 'Served in 15', text: 'Late food? Your discount grows automatically, every 5 minutes.' },
  ];
}

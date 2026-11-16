import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';

import { Health, HealthService } from '../../../core/health/health.service';
import { ApiError } from '../../../core/http/api-error';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Developer-facing page proving Phase 1 wiring: API, database, Redis, worker and Socket.IO. */
@Component({
  selector: 'wl-status-page',
  imports: [DatePipe, LoadingStateComponent, ErrorStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './status.page.html',
  styleUrl: './status.page.scss',
})
export class StatusPage implements OnInit {
  private readonly healthService = inject(HealthService);
  protected readonly realtime = inject(RealtimeService);

  protected readonly loading = signal(true);
  protected readonly health = signal<Health | null>(null);
  protected readonly error = signal<ApiError | null>(null);

  ngOnInit(): void {
    this.load();
    this.realtime.connect();
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.healthService.check().subscribe({
      next: (h) => {
        this.health.set(h);
        this.loading.set(false);
      },
      error: (e: ApiError) => {
        this.error.set(e);
        this.loading.set(false);
      },
    });
  }

  protected checks(h: Health) {
    return Object.entries(h.checks).map(([name, c]) => ({ name, ...c }));
  }
}

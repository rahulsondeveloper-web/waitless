import { DatePipe, TitleCasePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { debounceTime, distinctUntilChanged, filter } from 'rxjs';

import { TenantStatus } from '../../../core/auth/auth.models';
import { ApiError } from '../../../core/http/api-error';
import {
  Page,
  RestaurantAdminRow,
  STATUS_ACTIONS,
  StatusAction,
} from '../../../core/tenancy/tenancy.models';
import { TenancyService } from '../../../core/tenancy/tenancy.service';
import { EmptyStateComponent, ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';
import { StatusDialogComponent, StatusDialogData } from './status-dialog.component';

/** Super Admin → Restaurants (PRD §16 Restaurant Management). */
@Component({
  selector: 'wl-sa-restaurants',
  imports: [
    DatePipe,
    TitleCasePipe,
    ReactiveFormsModule,
    MatTableModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatMenuModule,
    MatPaginatorModule,
    LoadingStateComponent,
    ErrorStateComponent,
    EmptyStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './restaurants.page.html',
  styleUrl: './restaurants.page.scss',
})
export class RestaurantsPage implements OnInit {
  private readonly tenancy = inject(TenancyService);
  private readonly dialog = inject(MatDialog);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly statuses: (TenantStatus | 'all')[] = ['all', 'pending', 'active', 'suspended', 'deactivated', 'rejected'];
  protected readonly columns = ['restaurant', 'owner', 'city', 'plan', 'status', 'registered', 'actions'];
  protected actionsFor(row: RestaurantAdminRow): StatusAction[] {
    return STATUS_ACTIONS[row.status] ?? [];
  }

  protected readonly status = signal<TenantStatus | 'all'>('pending');
  protected readonly page = signal(1);
  protected readonly pageSize = signal(20);
  protected readonly result = signal<Page<RestaurantAdminRow> | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busyId = signal<string | null>(null);
  protected readonly search = new FormControl('', { nonNullable: true });

  ngOnInit(): void {
    this.search.valueChanges
      .pipe(debounceTime(350), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.load();
      });
    this.load();
  }

  protected setStatus(s: TenantStatus | 'all'): void {
    this.status.set(s);
    this.page.set(1);
    this.load();
  }

  protected onPage(e: PageEvent): void {
    this.page.set(e.pageIndex + 1);
    this.pageSize.set(e.pageSize);
    this.load();
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.tenancy
      .listRestaurants({
        status: this.status() === 'all' ? null : (this.status() as TenantStatus),
        q: this.search.value.trim() || null,
        page: this.page(),
        page_size: this.pageSize(),
      })
      .subscribe({
        next: (r) => {
          this.result.set(r);
          this.loading.set(false);
        },
        error: (e: ApiError) => {
          this.error.set(e);
          this.loading.set(false);
        },
      });
  }

  protected act(row: RestaurantAdminRow, action: StatusAction): void {
    const data: StatusDialogData = { action, restaurantName: row.name };
    this.dialog
      .open<StatusDialogComponent, StatusDialogData, string>(StatusDialogComponent, { data, width: '440px' })
      .afterClosed()
      .pipe(filter((reason): reason is string => reason !== undefined))
      .subscribe((reason) => {
        this.busyId.set(row.id);
        this.tenancy.changeStatus(row.id, action, reason).subscribe({
          next: (updated) => {
            this.busyId.set(null);
            this.snack.open(`${updated.name} is now ${updated.status}.`, 'OK', { duration: 3500 });
            this.load();
          },
          error: (e: ApiError) => {
            this.busyId.set(null);
            this.snack.open(e.message, 'Dismiss', { duration: 5000 });
          },
        });
      });
  }
}

import { CdkDragDrop, DragDropModule, moveItemInArray } from '@angular/cdk/drag-drop';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Observable, filter } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';
import { ApiError } from '../../../core/http/api-error';
import { Gallery, GalleryItem } from '../../../core/restaurant/restaurant.models';
import { RestaurantService } from '../../../core/restaurant/restaurant.service';
import { ConfirmData, ConfirmDialogComponent } from '../../../shared/ui/confirm-dialog/confirm-dialog.component';
import { checkImageFile, takeFile } from '../../../shared/ui/image-check';
import { ErrorStateComponent, LoadingStateComponent } from '../../../shared/ui/state/state.components';

/** Gallery management (PRD §5.3): max 5 photos, preview, replace, delete, reorder, captions. */
@Component({
  selector: 'wl-gallery-page',
  imports: [
    DragDropModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    LoadingStateComponent,
    ErrorStateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './gallery.page.html',
  styleUrl: './gallery.page.scss',
})
export class GalleryPage implements OnInit {
  private readonly restaurant = inject(RestaurantService);
  private readonly snack = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly auth = inject(AuthService);

  protected readonly canEdit = computed(() => this.auth.hasPermission('restaurant.gallery.manage'));
  protected readonly gallery = signal<Gallery | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busy = signal<string | null>(null); // item id, 'new' or 'order'
  protected readonly items = computed(() => this.gallery()?.items ?? []);
  protected readonly max = computed(() => this.gallery()?.max_photos ?? 5);
  protected readonly free = computed(() => Math.max(0, this.max() - this.items().length));
  protected readonly emptySlots = computed(() => Array.from({ length: this.free() }, (_, i) => i));

  ngOnInit(): void {
    this.restaurant.gallery().subscribe({ next: (g) => this.gallery.set(g), error: (e: ApiError) => this.error.set(e) });
  }

  protected add(event: Event): void {
    const file = takeFile(event);
    const problem = checkImageFile(file);
    if (problem) return void this.snack.open(problem, 'OK', { duration: 4000 });
    this.run('new', this.restaurant.addPhoto(file!), 'Photo added.');
  }

  protected replace(item: GalleryItem, event: Event): void {
    const file = takeFile(event);
    const problem = checkImageFile(file);
    if (problem) return void this.snack.open(problem, 'OK', { duration: 4000 });
    this.run(item.id, this.restaurant.replacePhoto(item.id, file!), 'Photo replaced.');
  }

  protected saveCaption(item: GalleryItem, value: string): void {
    const caption = value.trim();
    if (caption === item.caption) return;
    this.run(item.id, this.restaurant.captionPhoto(item.id, caption), 'Caption saved.');
  }

  protected remove(item: GalleryItem): void {
    const data: ConfirmData = {
      title: 'Delete this photo?',
      message: 'It is removed from your storefront gallery immediately.',
      confirm: 'Delete',
      danger: true,
    };
    this.dialog
      .open(ConfirmDialogComponent, { data, width: '400px' })
      .afterClosed()
      .pipe(filter(Boolean))
      .subscribe(() => this.run(item.id, this.restaurant.deletePhoto(item.id), 'Photo deleted.'));
  }

  protected drop(event: CdkDragDrop<GalleryItem[]>): void {
    if (event.previousIndex === event.currentIndex) return;
    const reordered = [...this.items()];
    moveItemInArray(reordered, event.previousIndex, event.currentIndex);
    this.gallery.update((g) => (g ? { ...g, items: reordered } : g)); // optimistic
    this.run('order', this.restaurant.reorderPhotos(reordered.map((i) => i.id)), 'Order saved.');
  }

  /** Keyboard alternative to dragging. */
  protected move(index: number, delta: -1 | 1): void {
    const target = index + delta;
    if (target < 0 || target >= this.items().length) return;
    this.drop({ previousIndex: index, currentIndex: target } as CdkDragDrop<GalleryItem[]>);
  }

  private run(key: string, obs: Observable<Gallery>, message: string): void {
    this.busy.set(key);
    obs.subscribe({
      next: (g) => {
        this.gallery.set(g);
        this.busy.set(null);
        this.snack.open(message, undefined, { duration: 2000 });
      },
      error: (e: ApiError) => {
        this.busy.set(null);
        this.snack.open(e.message, 'Dismiss', { duration: 6000 });
        this.ngOnInit(); // re-sync after a failed optimistic change
      },
    });
  }
}

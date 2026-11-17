import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { forkJoin, of, switchMap } from 'rxjs';

import { ApiError } from '../../../core/http/api-error';
import { AdminItem, ItemOptionsInput, MenuService } from '../../../core/restaurant/menu.service';
import { Branch } from '../../../core/tenancy/tenancy.models';

export interface OptionsDialogData {
  item: AdminItem;
  branches: Branch[];
}

interface Group {
  name: string;
  min_select: number;
  max_select: number;
  addons: { name: string; price: string }[];
}
interface Window {
  weekday: number;
  from_time: string;
  to_time: string;
}
interface BranchRow {
  branch: Branch;
  is_available: boolean;
  price_override: string;
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Sizes (variants), extras (add-on groups), serving times and per-branch price/availability (PRD §7.3). */
@Component({
  selector: 'wl-options-dialog',
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatIconModule, MatTabsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './options-dialog.component.html',
  styleUrl: './options-dialog.component.scss',
})
export class OptionsDialogComponent {
  protected readonly data = inject<OptionsDialogData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<OptionsDialogComponent, AdminItem>);
  private readonly menu = inject(MenuService);
  protected readonly days = DAYS;
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected variants = this.data.item.variants.map((v) => ({ name: v.name, price: String(+v.price) }));
  protected groups: Group[] = this.data.item.addon_groups.map((g) => ({
    name: g.name,
    min_select: g.min_select,
    max_select: g.max_select,
    addons: g.addons.map((a) => ({ name: a.name, price: String(+a.price) })),
  }));
  protected windows: Window[] = this.data.item.availability.map((w) => ({
    weekday: w.weekday,
    from_time: w.from_time.slice(0, 5),
    to_time: w.to_time.slice(0, 5),
  }));
  protected limited = this.windows.length > 0;
  protected branchRows: BranchRow[] = this.data.branches.map((b) => {
    const o = this.data.item.branch_overrides.find((x) => x.branch_id === b.id);
    return { branch: b, is_available: o?.is_available ?? true, price_override: o?.price_override ? String(+o.price_override) : '' };
  });

  protected addVariant(): void {
    this.variants = [...this.variants, { name: '', price: this.data.item.base_price }];
  }
  protected removeVariant(i: number): void {
    this.variants = this.variants.filter((_, n) => n !== i);
  }
  protected addGroup(): void {
    this.groups = [...this.groups, { name: '', min_select: 0, max_select: 1, addons: [{ name: '', price: '0' }] }];
  }
  protected removeGroup(i: number): void {
    this.groups = this.groups.filter((_, n) => n !== i);
  }
  protected addAddon(g: Group): void {
    g.addons = [...g.addons, { name: '', price: '0' }];
  }
  protected removeAddon(g: Group, i: number): void {
    g.addons = g.addons.filter((_, n) => n !== i);
  }
  protected setLimited(on: boolean): void {
    this.limited = on;
    if (on && !this.windows.length) this.windows = DAYS.map((_, d) => ({ weekday: d, from_time: '12:00', to_time: '15:00' }));
  }
  protected addWindow(): void {
    this.windows = [...this.windows, { weekday: 0, from_time: '12:00', to_time: '15:00' }];
  }
  protected removeWindow(i: number): void {
    this.windows = this.windows.filter((_, n) => n !== i);
  }

  protected save(): void {
    const body: ItemOptionsInput = {
      variants: this.variants.filter((v) => v.name.trim()).map((v) => ({ name: v.name.trim(), price: String(+v.price || 0) })),
      addon_groups: this.groups
        .filter((g) => g.name.trim() && g.addons.some((a) => a.name.trim()))
        .map((g) => ({
          name: g.name.trim(),
          min_select: Math.max(0, Math.floor(+g.min_select || 0)),
          max_select: Math.max(1, Math.floor(+g.max_select || 1)),
          addons: g.addons.filter((a) => a.name.trim()).map((a) => ({ name: a.name.trim(), price: String(+a.price || 0) })),
        })),
      availability: this.limited
        ? this.windows.filter((w) => w.from_time < w.to_time).map((w) => ({ ...w, weekday: +w.weekday }))
        : [],
    };
    this.saving.set(true);
    this.error.set(null);
    const id = this.data.item.id;
    this.menu
      .setOptions(id, body)
      .pipe(
        switchMap((saved) => {
          const changed = this.branchRows.filter((r) => {
            const o = saved.branch_overrides.find((x) => x.branch_id === r.branch.id);
            const price = r.price_override.trim() ? String(+r.price_override) : null;
            return (o?.is_available ?? true) !== r.is_available || (o?.price_override ? String(+o.price_override) : null) !== price;
          });
          if (!changed.length) return of(saved);
          return forkJoin(
            changed.map((r) =>
              this.menu.setBranchOverride(id, r.branch.id, {
                is_available: r.is_available,
                price_override: r.price_override.trim() ? String(+r.price_override) : null,
              }),
            ),
          ).pipe(switchMap((all) => of(all[all.length - 1])));
        }),
      )
      .subscribe({
        next: (item) => this.ref.close(item),
        error: (e: ApiError) => {
          this.saving.set(false);
          this.error.set(e.message);
        },
      });
  }
}

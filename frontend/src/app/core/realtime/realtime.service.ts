import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import { Socket, io } from 'socket.io-client';

import { AuthService } from '../auth/auth.service';
import { APP_CONFIG } from '../config/app-config';

export type RealtimeStatus = 'idle' | 'connecting' | 'connected' | 'disconnected';

/**
 * Single Socket.IO connection for the app (namespace /rt).
 * - Sends the current access token on every (re)connect; rooms are re-joined after reconnecting.
 * - Measures the server clock offset so countdowns (serving timer, PRD §14) use server time.
 */
@Injectable({ providedIn: 'root' })
export class RealtimeService implements OnDestroy {
  private readonly auth = inject(AuthService);
  private socket?: Socket;
  private authed = false;
  private readonly rooms = new Map<string, Record<string, string>>(); // key → subscribe payload
  // Listeners survive socket replacement (e.g. upgrading an anonymous connection to a signed-in one).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private readonly handlers = new Map<string, Set<(...args: any[]) => void>>();
  private readonly _status = signal<RealtimeStatus>('idle');
  private readonly _offsetMs = signal(0);
  private readonly _reconnects = signal(0);

  readonly status = this._status.asReadonly();
  readonly connected = computed(() => this._status() === 'connected');
  /** serverNow = Date.now() + clockOffsetMs() */
  readonly clockOffsetMs = this._offsetMs.asReadonly();
  /** Bumps on every reconnect: pushes may have been missed while offline. */
  readonly reconnects = this._reconnects.asReadonly();

  /** Anonymous connection (public pages). Upgraded automatically when a room needs a signed-in user. */
  connect(): void {
    if (this.socket) return;
    this.open(false);
  }

  /** Join a staff room for one branch. Resolves false when not allowed. */
  subscribeBranch(branchId: string): Promise<boolean> {
    return this.join(`branch:${branchId}`, { kind: 'branch_staff', branch_id: branchId }, true);
  }

  unsubscribeBranch(branchId: string): void {
    this.leave(`branch:${branchId}`, { kind: 'branch_staff', branch_id: branchId });
  }

  /** My own notifications (room u:{me}); needs a signed-in user. */
  subscribeUser(): Promise<boolean> {
    return this.join('user', { kind: 'user' }, true);
  }

  unsubscribeUser(): void {
    this.leave('user', { kind: 'user' });
  }

  /** Public "queue changed" pings of one branch (no personal data). */
  subscribeQueue(tenantId: string, branchId: string): Promise<boolean> {
    return this.join(`queue:${branchId}`, { kind: 'branch_queue', tenant_id: tenantId, branch_id: branchId }, false);
  }

  unsubscribeQueue(tenantId: string, branchId: string): void {
    this.leave(`queue:${branchId}`, { kind: 'branch_queue', tenant_id: tenantId, branch_id: branchId });
  }

  /** Public "this restaurant's pages changed" pings (menu, profile, gallery…) — no data at all. */
  subscribeStorefront(slug: string): Promise<boolean> {
    return this.join(`storefront:${slug}`, { kind: 'storefront', slug }, false);
  }

  unsubscribeStorefront(slug: string): void {
    this.leave(`storefront:${slug}`, { kind: 'storefront', slug });
  }

  /** Guests at a table: live order updates, authorised by the table token (no account needed). */
  subscribeTableSession(token: string): Promise<boolean> {
    return this.join('table', { kind: 'table_session', token }, false);
  }

  unsubscribeTableSession(token: string): void {
    this.leave('table', { kind: 'table_session', token });
  }

  private async join(key: string, payload: Record<string, string>, needsAuth: boolean): Promise<boolean> {
    if (!this.socket || (needsAuth && !this.authed)) {
      const withAuth = needsAuth || this.authed; // never downgrade a signed-in connection
      this.disconnect(false);
      this.open(withAuth);
    }
    const ok = await this.emitSubscribe(payload);
    if (ok) this.rooms.set(key, payload);
    return ok;
  }

  private leave(key: string, payload: Record<string, string>): void {
    this.rooms.delete(key);
    this.socket?.emit('unsubscribe', payload);
  }

  on<T>(event: string, handler: (payload: T) => void): () => void {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const h = handler as (...args: any[]) => void;
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(h);
    this.socket?.on(event, h);
    return () => {
      this.handlers.get(event)?.delete(h);
      this.socket?.off(event, h);
    };
  }

  serverNow(): number {
    return Date.now() + this._offsetMs();
  }

  disconnect(clearRooms = true): void {
    this.socket?.disconnect();
    this.socket = undefined;
    this.authed = false;
    if (clearRooms) this.rooms.clear();
    this._status.set('idle');
  }

  ngOnDestroy(): void {
    this.disconnect();
  }

  private open(withAuth: boolean): void {
    this._status.set('connecting');
    this.authed = withAuth;
    this.socket = io(APP_CONFIG.socketNamespace, {
      path: APP_CONFIG.socketPath,
      // A function: the *current* token is sent on every reconnect (tokens rotate every 15 minutes).
      auth: withAuth ? (cb) => cb({ token: this.auth.token() ?? '' }) : undefined,
      transports: ['websocket', 'polling'],
    });
    for (const [event, set] of this.handlers) for (const h of set) this.socket.on(event, h);
    // Only a reconnect of the *same* socket can have missed pushes (replacing an anonymous socket by a
    // signed-in one happens in milliseconds and is not counted).
    let connectedBefore = false;
    this.socket.on('connect', () => {
      this._status.set('connected');
      if (connectedBefore) this._reconnects.update((n) => n + 1);
      connectedBefore = true;
      this.syncClock();
      for (const payload of this.rooms.values()) void this.emitSubscribe(payload);
    });
    this.socket.on('disconnect', () => this._status.set('disconnected'));
    this.socket.on('connect_error', () => this._status.set('disconnected'));
  }

  private emitSubscribe(payload: Record<string, string>): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.socket) return resolve(false);
      this.socket.timeout(8000).emit('subscribe', payload, (err: unknown, res?: { ok: boolean }) =>
        resolve(!err && !!res?.ok),
      );
    });
  }

  private syncClock(): void {
    const sentAt = Date.now();
    this.socket?.emit('time.sync', null, (res: { server_time: string }) => {
      const receivedAt = Date.now();
      const serverMs = Date.parse(res.server_time);
      // assume symmetric latency
      this._offsetMs.set(Math.round(serverMs - (sentAt + receivedAt) / 2));
    });
  }
}

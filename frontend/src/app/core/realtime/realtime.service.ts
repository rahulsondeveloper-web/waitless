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

  readonly status = this._status.asReadonly();
  readonly connected = computed(() => this._status() === 'connected');
  /** serverNow = Date.now() + clockOffsetMs() */
  readonly clockOffsetMs = this._offsetMs.asReadonly();

  /** Anonymous connection (public pages). Upgraded automatically when a room needs a signed-in user. */
  connect(): void {
    if (this.socket) return;
    this.open(false);
  }

  /** Join a staff room for one branch. Resolves false when not allowed. */
  async subscribeBranch(branchId: string): Promise<boolean> {
    if (!this.socket || !this.authed) {
      this.disconnect(false);
      this.open(true);
    }
    const payload = { kind: 'branch_staff', branch_id: branchId };
    const ok = await this.emitSubscribe(payload);
    if (ok) this.rooms.set(`branch:${branchId}`, payload);
    return ok;
  }

  unsubscribeBranch(branchId: string): void {
    this.rooms.delete(`branch:${branchId}`);
    this.socket?.emit('unsubscribe', { branch_id: branchId });
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
    this.socket.on('connect', () => {
      this._status.set('connected');
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

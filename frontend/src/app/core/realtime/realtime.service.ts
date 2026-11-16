import { Injectable, OnDestroy, computed, signal } from '@angular/core';
import { Socket, io } from 'socket.io-client';

import { APP_CONFIG } from '../config/app-config';

export type RealtimeStatus = 'idle' | 'connecting' | 'connected' | 'disconnected';

/**
 * Single Socket.IO connection for the app (namespace /rt).
 * Also measures the server clock offset so countdowns (serving timer, PRD §14) use server time.
 */
@Injectable({ providedIn: 'root' })
export class RealtimeService implements OnDestroy {
  private socket?: Socket;
  private readonly _status = signal<RealtimeStatus>('idle');
  private readonly _offsetMs = signal(0);

  readonly status = this._status.asReadonly();
  readonly connected = computed(() => this._status() === 'connected');
  /** serverNow = Date.now() + clockOffsetMs() */
  readonly clockOffsetMs = this._offsetMs.asReadonly();

  connect(auth?: Record<string, string>): void {
    if (this.socket) return;
    this._status.set('connecting');
    this.socket = io(APP_CONFIG.socketNamespace, {
      path: APP_CONFIG.socketPath,
      auth,
      transports: ['websocket', 'polling'],
    });
    this.socket.on('connect', () => {
      this._status.set('connected');
      this.syncClock();
    });
    this.socket.on('disconnect', () => this._status.set('disconnected'));
    this.socket.on('connect_error', () => this._status.set('disconnected'));
  }

  on<T>(event: string, handler: (payload: T) => void): () => void {
    this.socket?.on(event, handler);
    return () => this.socket?.off(event, handler);
  }

  serverNow(): number {
    return Date.now() + this._offsetMs();
  }

  disconnect(): void {
    this.socket?.disconnect();
    this.socket = undefined;
    this._status.set('idle');
  }

  ngOnDestroy(): void {
    this.disconnect();
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

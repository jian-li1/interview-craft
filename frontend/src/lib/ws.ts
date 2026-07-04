import { env } from "@/lib/env";
import type { ClientEvent, ServerEvent } from "@/lib/types";

export type ConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed";

type EventHandler = (event: ServerEvent) => void;
type StateHandler = (state: ConnectionState) => void;

const PING_INTERVAL_MS = 25_000;
const MAX_BACKOFF_MS = 15_000;
const BASE_BACKOFF_MS = 500;

/**
 * Typed wrapper around the chat WebSocket protocol defined in spec 01 §7.
 * Handles reconnect with exponential backoff + jitter, ping keepalive, and
 * typed event dispatch.
 */
export class ChatSocket {
  private conversationId: string;
  private ws: WebSocket | null = null;
  private state: ConnectionState = "idle";
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private manuallyClosed = false;
  private eventHandlers = new Set<EventHandler>();
  private stateHandlers = new Set<StateHandler>();

  constructor(conversationId: string) {
    this.conversationId = conversationId;
  }

  /** Subscribe to parsed server events. Returns an unsubscribe function. */
  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  /** Subscribe to connection-state transitions. Returns an unsubscribe function. */
  onStateChange(handler: StateHandler): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  /** Current connection state (see `ConnectionState`). */
  getState(): ConnectionState {
    return this.state;
  }

  /**
   * Opens the socket. Clears `manuallyClosed` first so a fresh `connect()`
   * call after a prior `close()` is allowed to reconnect (without this reset,
   * a stale `manuallyClosed = true` from an earlier close would make
   * `scheduleReconnect`/`onclose` treat the new connection as intentionally
   * closed too).
   */
  connect(): void {
    this.manuallyClosed = false;
    this.open();
  }

  private setState(state: ConnectionState) {
    this.state = state;
    this.stateHandlers.forEach((h) => h(state));
  }

  private open() {
    this.setState(this.reconnectAttempt > 0 ? "reconnecting" : "connecting");
    const url = `${env.wsBaseUrl}/ws/chat/${this.conversationId}`;

    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      this.reconnectAttempt = 0;
      this.setState("open");
      this.startPing();
    };

    socket.onmessage = (evt) => {
      let parsed: ServerEvent;
      try {
        parsed = JSON.parse(evt.data as string) as ServerEvent;
      } catch {
        return;
      }
      this.eventHandlers.forEach((h) => h(parsed));
    };

    socket.onclose = () => {
      this.stopPing();
      // `manuallyClosed` distinguishes an intentional close() (e.g. the
      // owning component unmounted, or the conversation changed) from a
      // dropped connection (server restart, network blip, proxy timeout).
      // Only the latter should trigger a reconnect attempt.
      if (!this.manuallyClosed) {
        this.scheduleReconnect();
      } else {
        this.setState("closed");
      }
    };

    socket.onerror = () => {
      // Intentionally a no-op: the WebSocket spec guarantees `onclose` fires
      // immediately after `onerror` for any connection failure, so all
      // reconnect/state-transition logic lives in `onclose` to avoid running
      // it twice (once from onerror, once from onclose) for the same event.
    };
  }

  /**
   * Schedules the next reconnect attempt using exponential backoff with
   * jitter: delay doubles each attempt (capped at MAX_BACKOFF_MS) and gets
   * up to 30% random jitter added on top. The exponential growth avoids
   * hammering a struggling backend; the jitter avoids a "thundering herd"
   * where every client that dropped at the same moment (e.g. a server
   * restart) reconnects in perfect lockstep and re-overwhelms it.
   */
  private scheduleReconnect() {
    this.setState("reconnecting");
    const attempt = this.reconnectAttempt;
    const backoff = Math.min(BASE_BACKOFF_MS * 2 ** attempt, MAX_BACKOFF_MS);
    const jitter = Math.random() * 0.3 * backoff;
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      if (!this.manuallyClosed) this.open();
    }, backoff + jitter);
  }

  // Keepalive: many intermediaries (load balancers, proxies, browsers)
  // silently drop idle WebSocket connections after ~30-60s of inactivity.
  // Sending a lightweight ping on an interval keeps the connection alive
  // and lets the server's own liveness checks see recent client activity.
  private startPing() {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      this.send({ type: "ping" });
    }, PING_INTERVAL_MS);
  }

  private stopPing() {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  /** Sends a typed client event if the socket is currently open; silently drops otherwise. */
  send(event: ClientEvent): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(event));
    }
  }

  /** Sends a user chat message to the agent. */
  sendUserMessage(content: string): void {
    this.send({ type: "user_message", content });
  }

  /** Approves or requests changes to a proposed task plan (HITL plan-approval flow). */
  sendPlanDecision(decision: "approve" | "modify", feedback: string | null): void {
    this.send({ type: "plan_decision", decision, feedback });
  }

  /** Requests the agent run be cancelled. */
  sendStop(): void {
    this.send({ type: "stop" });
  }

  /**
   * Closes the socket intentionally. Sets `manuallyClosed` first so the
   * `onclose` handler above knows not to schedule a reconnect, then tears
   * down any pending reconnect timer and the ping interval before closing
   * the underlying WebSocket.
   */
  close(): void {
    this.manuallyClosed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.stopPing();
    this.ws?.close();
    this.ws = null;
  }
}

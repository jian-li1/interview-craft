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

  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  onStateChange(handler: StateHandler): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  getState(): ConnectionState {
    return this.state;
  }

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
      if (!this.manuallyClosed) {
        this.scheduleReconnect();
      } else {
        this.setState("closed");
      }
    };

    socket.onerror = () => {
      // onclose will fire right after; let that path own reconnect scheduling.
    };
  }

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

  send(event: ClientEvent): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(event));
    }
  }

  sendUserMessage(content: string): void {
    this.send({ type: "user_message", content });
  }

  sendPlanDecision(decision: "approve" | "modify", feedback: string | null): void {
    this.send({ type: "plan_decision", decision, feedback });
  }

  sendStop(): void {
    this.send({ type: "stop" });
  }

  close(): void {
    this.manuallyClosed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.stopPing();
    this.ws?.close();
    this.ws = null;
  }
}

type Channel = "prices" | "alerts" | "signals" | "system";

type MessageHandler = (data: unknown) => void;

interface WSMessage {
  channel: Channel;
  data: unknown;
}

class TradingWebSocket {
  private ws: WebSocket | null = null;
  private handlers = new Map<Channel, Set<MessageHandler>>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private baseReconnectDelay = 1000;
  private url: string;
  private _connected = false;
  private connectionListeners = new Set<(connected: boolean) => void>();

  constructor(url: string) {
    this.url = url;
  }

  get connected(): boolean {
    return this._connected;
  }

  onConnectionChange(listener: (connected: boolean) => void): () => void {
    this.connectionListeners.add(listener);
    return () => this.connectionListeners.delete(listener);
  }

  private setConnected(value: boolean) {
    this._connected = value;
    this.connectionListeners.forEach((listener) => listener(value));
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.setConnected(true);
        this.reconnectAttempts = 0;
        console.log("[WS] Connected to", this.url);
      };

      this.ws.onmessage = (event: MessageEvent) => {
        this.onMessage(event);
      };

      this.ws.onclose = (event) => {
        this.setConnected(false);
        console.log("[WS] Disconnected:", event.code, event.reason);
        if (event.code !== 1000) {
          this.reconnect();
        }
      };

      this.ws.onerror = (error) => {
        console.error("[WS] Error:", error);
        this.setConnected(false);
      };
    } catch (error) {
      console.error("[WS] Failed to connect:", error);
      this.reconnect();
    }
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectAttempts = this.maxReconnectAttempts;

    if (this.ws) {
      this.ws.close(1000, "Client disconnect");
      this.ws = null;
    }
    this.setConnected(false);
  }

  subscribe(channel: Channel, handler: MessageHandler): void {
    if (!this.handlers.has(channel)) {
      this.handlers.set(channel, new Set());
    }
    this.handlers.get(channel)!.add(handler);

    // Send subscribe message to server
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "subscribe", channel }));
    }
  }

  unsubscribe(channel: Channel, handler: MessageHandler): void {
    const channelHandlers = this.handlers.get(channel);
    if (channelHandlers) {
      channelHandlers.delete(handler);
      if (channelHandlers.size === 0) {
        this.handlers.delete(channel);
        // Send unsubscribe message to server
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: "unsubscribe", channel }));
        }
      }
    }
  }

  send(channel: Channel, data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ channel, data }));
    } else {
      console.warn("[WS] Cannot send, not connected");
    }
  }

  private onMessage(event: MessageEvent): void {
    try {
      const message: WSMessage = JSON.parse(event.data);
      const { channel, data } = message;

      const channelHandlers = this.handlers.get(channel);
      if (channelHandlers) {
        channelHandlers.forEach((handler) => {
          try {
            handler(data);
          } catch (error) {
            console.error(`[WS] Handler error on channel ${channel}:`, error);
          }
        });
      }
    } catch (error) {
      console.error("[WS] Failed to parse message:", error);
    }
  }

  private reconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("[WS] Max reconnect attempts reached");
      return;
    }

    const delay = Math.min(
      this.baseReconnectDelay * Math.pow(2, this.reconnectAttempts),
      30000
    );

    console.log(
      `[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }
}

export const tradingWS = new TradingWebSocket(
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/api/ws"
);

export type { Channel, MessageHandler };

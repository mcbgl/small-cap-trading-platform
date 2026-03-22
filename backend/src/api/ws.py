"""
WebSocket hub for real-time data streaming.

Channels:
- prices:   Real-time price ticks
- alerts:   Trading alerts and notifications
- signals:  New signal detections
- system:   System status updates and kill-switch notifications
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections and channel subscriptions."""

    def __init__(self):
        # channel_name -> set of WebSocket connections
        self._channels: dict[str, set[WebSocket]] = {}
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        logger.info(f"WebSocket connected: {websocket.client}")

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        for channel_subs in self._channels.values():
            channel_subs.discard(websocket)
        logger.info(f"WebSocket disconnected: {websocket.client}")

    def subscribe(self, websocket: WebSocket, channel: str) -> None:
        if channel not in self._channels:
            self._channels[channel] = set()
        self._channels[channel].add(websocket)
        logger.debug(f"Subscribed {websocket.client} to channel '{channel}'")

    def unsubscribe(self, websocket: WebSocket, channel: str) -> None:
        if channel in self._channels:
            self._channels[channel].discard(websocket)

    async def broadcast_to_channel(self, channel: str, data: dict) -> None:
        """Broadcast a message to all subscribers of a channel."""
        subscribers = self._channels.get(channel, set())
        dead: list[WebSocket] = []
        for ws in subscribers:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_personal(self, websocket: WebSocket, data: dict) -> None:
        await websocket.send_json(data)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint supporting channel-based subscriptions.

    Clients send JSON messages:
        {"action": "subscribe", "channel": "prices"}
        {"action": "unsubscribe", "channel": "prices"}
        {"action": "ping"}

    Server sends:
        {"type": "subscribed", "channel": "prices"}
        {"type": "pong", "timestamp": "..."}
        {"type": "prices", "data": {...}}   (channel messages)
    """
    await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_personal(websocket, {"type": "error", "message": "Invalid JSON"})
                continue

            action = msg.get("action", "")

            if action == "subscribe":
                channel = msg.get("channel", "")
                if channel in ("prices", "alerts", "signals", "system"):
                    manager.subscribe(websocket, channel)
                    await manager.send_personal(
                        websocket, {"type": "subscribed", "channel": channel}
                    )
                else:
                    await manager.send_personal(
                        websocket,
                        {"type": "error", "message": f"Unknown channel: {channel}"},
                    )

            elif action == "unsubscribe":
                channel = msg.get("channel", "")
                manager.unsubscribe(websocket, channel)
                await manager.send_personal(
                    websocket, {"type": "unsubscribed", "channel": channel}
                )

            elif action == "ping":
                await manager.send_personal(
                    websocket,
                    {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()},
                )

            else:
                await manager.send_personal(
                    websocket, {"type": "error", "message": f"Unknown action: {action}"}
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)

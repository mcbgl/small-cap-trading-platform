"use client";

import { useEffect } from "react";
import { tradingWS } from "@/lib/ws";
import { useSystemStore } from "@/lib/stores/system";
import { useSignalsStore } from "@/lib/stores/signals";

/**
 * Client component that initializes the WebSocket connection
 * and wires up Zustand store subscriptions on mount.
 * Renders nothing -- purely a side-effect component.
 */
export default function WebSocketInit() {
  useEffect(() => {
    // Connect the WebSocket
    tradingWS.connect();

    // Initialize store WebSocket subscriptions
    const cleanupSystem = useSystemStore.getState().initWebSocket();
    const cleanupSignals = useSignalsStore.getState().initWebSocket();

    return () => {
      cleanupSignals();
      cleanupSystem();
      tradingWS.disconnect();
    };
  }, []);

  return null;
}

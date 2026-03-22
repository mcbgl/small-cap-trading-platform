"use client";

import { useState, useEffect, useCallback } from "react";
import { Search, Bell, Wifi, WifiOff } from "lucide-react";
import { useAlertsStore } from "@/lib/stores/alerts";
import { tradingWS } from "@/lib/ws";
import Badge from "@/components/common/Badge";
import StatusDot from "@/components/common/StatusDot";

export default function TopBar() {
  const [searchQuery, setSearchQuery] = useState("");
  const [wsConnected, setWsConnected] = useState(false);
  const unreadCount = useAlertsStore((s) => s.unreadCount);

  useEffect(() => {
    const unsubscribe = tradingWS.onConnectionChange(setWsConnected);
    setWsConnected(tradingWS.connected);
    return unsubscribe;
  }, []);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      const input = document.getElementById("global-search") as HTMLInputElement;
      input?.focus();
    }
  }, []);

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return (
    <header
      className="fixed top-0 right-0 h-14 z-30 flex items-center justify-between px-6 border-b"
      style={{
        left: "60px",
        backgroundColor: "var(--bg-secondary)",
        borderColor: "var(--border)",
      }}
    >
      {/* Search */}
      <div className="flex items-center gap-2 flex-1 max-w-md">
        <div
          className="flex items-center gap-2 w-full rounded-md px-3 py-1.5 border"
          style={{
            backgroundColor: "var(--bg-primary)",
            borderColor: "var(--border)",
          }}
        >
          <Search size={14} style={{ color: "var(--text-muted)" }} />
          <input
            id="global-search"
            type="text"
            placeholder="Search tickers, signals..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-transparent border-none outline-none text-sm flex-1"
            style={{ color: "var(--text-primary)" }}
          />
          <kbd
            className="hidden sm:inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs"
            style={{
              backgroundColor: "var(--bg-hover)",
              color: "var(--text-muted)",
              border: "1px solid var(--border)",
            }}
          >
            Cmd+K
          </kbd>
        </div>
      </div>

      {/* Right section */}
      <div className="flex items-center gap-4">
        {/* Paper/Live Mode Toggle */}
        <Badge variant="success">PAPER</Badge>

        {/* Alerts */}
        <button className="relative p-1.5 rounded-md transition-colors hover:opacity-80">
          <Bell size={18} style={{ color: "var(--text-secondary)" }} />
          {unreadCount > 0 && (
            <span
              className="absolute -top-0.5 -right-0.5 flex items-center justify-center h-4 min-w-4 rounded-full text-[10px] font-bold"
              style={{
                backgroundColor: "var(--accent-red)",
                color: "white",
              }}
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>

        {/* Connection Status */}
        <div className="flex items-center gap-1.5">
          {wsConnected ? (
            <Wifi size={14} style={{ color: "var(--accent-green)" }} />
          ) : (
            <WifiOff size={14} style={{ color: "var(--accent-red)" }} />
          )}
          <StatusDot
            status={wsConnected ? "connected" : "disconnected"}
            size="sm"
            pulse={wsConnected}
          />
        </div>
      </div>
    </header>
  );
}

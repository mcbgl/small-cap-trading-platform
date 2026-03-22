"use client";

import { Settings, Cpu, HardDrive, Gauge } from "lucide-react";
import StatusDot from "@/components/common/StatusDot";

interface ServiceStatus {
  name: string;
  status: "connected" | "disconnected" | "degraded";
  description: string;
  details: string;
}

const services: ServiceStatus[] = [
  {
    name: "PostgreSQL",
    status: "disconnected",
    description: "Primary relational database",
    details: "Port 5432",
  },
  {
    name: "QuestDB",
    status: "disconnected",
    description: "Time-series database for market data",
    details: "Port 9009 (ILP) / 8812 (PG)",
  },
  {
    name: "Redis",
    status: "disconnected",
    description: "Cache and message broker",
    details: "Port 6379",
  },
  {
    name: "Ollama / Qwen",
    status: "disconnected",
    description: "Local LLM for real-time analysis",
    details: "Port 11434",
  },
  {
    name: "Polygon WebSocket",
    status: "disconnected",
    description: "Real-time market data feed",
    details: "wss://socket.polygon.io",
  },
  {
    name: "EDGAR Feed",
    status: "disconnected",
    description: "SEC filing data stream",
    details: "efts.sec.gov",
  },
];

interface ResourceGauge {
  label: string;
  value: number;
  unit: string;
}

const resources: ResourceGauge[] = [
  { label: "CPU", value: 0, unit: "%" },
  { label: "RAM", value: 0, unit: "%" },
  { label: "GPU", value: 0, unit: "%" },
];

export default function SystemPage() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1
          className="text-2xl font-bold flex items-center gap-2"
          style={{ color: "var(--text-primary)" }}
        >
          <Settings size={24} style={{ color: "var(--accent-blue)" }} />
          System Health
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Monitor infrastructure and service connectivity
        </p>
      </div>

      {/* Service Status Cards */}
      <div>
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          Services
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {services.map((service) => (
            <div
              key={service.name}
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-card)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <span
                  className="text-sm font-semibold"
                  style={{ color: "var(--text-primary)" }}
                >
                  {service.name}
                </span>
                <StatusDot status={service.status} size="md" />
              </div>
              <p className="text-xs mb-1" style={{ color: "var(--text-secondary)" }}>
                {service.description}
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {service.details}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Resource Usage */}
      <div>
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          Resource Usage
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {resources.map((resource) => (
            <div
              key={resource.label}
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-card)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-center gap-2 mb-3">
                {resource.label === "CPU" && (
                  <Cpu size={16} style={{ color: "var(--accent-blue)" }} />
                )}
                {resource.label === "RAM" && (
                  <HardDrive size={16} style={{ color: "var(--accent-purple)" }} />
                )}
                {resource.label === "GPU" && (
                  <Gauge size={16} style={{ color: "var(--accent-green)" }} />
                )}
                <span
                  className="text-sm font-semibold"
                  style={{ color: "var(--text-primary)" }}
                >
                  {resource.label}
                </span>
                <span
                  className="ml-auto text-sm font-mono"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {resource.value}{resource.unit}
                </span>
              </div>
              <div
                className="h-2 rounded-full w-full"
                style={{ backgroundColor: "var(--bg-hover)" }}
              >
                <div
                  className="h-2 rounded-full transition-all duration-500"
                  style={{
                    width: `${resource.value}%`,
                    backgroundColor:
                      resource.value > 80
                        ? "var(--accent-red)"
                        : resource.value > 60
                          ? "var(--accent-amber)"
                          : "var(--accent-green)",
                    minWidth: resource.value > 0 ? "4px" : "0",
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* System Info */}
      <div
        className="rounded-lg border p-4"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          Platform Info
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
          <div>
            <span style={{ color: "var(--text-muted)" }}>Mode</span>
            <p className="font-medium mt-0.5" style={{ color: "var(--accent-green)" }}>
              Paper Trading
            </p>
          </div>
          <div>
            <span style={{ color: "var(--text-muted)" }}>Frontend</span>
            <p className="font-medium mt-0.5" style={{ color: "var(--text-secondary)" }}>
              Next.js 15
            </p>
          </div>
          <div>
            <span style={{ color: "var(--text-muted)" }}>Backend</span>
            <p className="font-medium mt-0.5" style={{ color: "var(--text-secondary)" }}>
              FastAPI
            </p>
          </div>
          <div>
            <span style={{ color: "var(--text-muted)" }}>Uptime</span>
            <p className="font-medium mt-0.5" style={{ color: "var(--text-secondary)" }}>
              ---
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

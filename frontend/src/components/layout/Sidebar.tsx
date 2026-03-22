"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Wallet,
  Search,
  FileText,
  Zap,
  Shield,
  BarChart3,
  Settings,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

const navItems: NavItem[] = [
  { href: "/", label: "Home", icon: <LayoutDashboard size={20} /> },
  { href: "/portfolio", label: "Portfolio", icon: <Wallet size={20} /> },
  { href: "/screener", label: "Screener", icon: <Search size={20} /> },
  { href: "/filings", label: "Filings", icon: <FileText size={20} /> },
  { href: "/signals", label: "Signals", icon: <Zap size={20} /> },
  { href: "/risk", label: "Risk", icon: <Shield size={20} /> },
  { href: "/backtest", label: "Backtest", icon: <BarChart3 size={20} /> },
  { href: "/system", label: "System", icon: <Settings size={20} /> },
];

export default function Sidebar() {
  const [expanded, setExpanded] = useState(false);
  const pathname = usePathname();

  return (
    <aside
      className="fixed left-0 top-0 h-full z-40 flex flex-col border-r transition-all duration-200"
      style={{
        width: expanded ? "200px" : "60px",
        backgroundColor: "var(--bg-secondary)",
        borderColor: "var(--border)",
      }}
    >
      {/* Logo area */}
      <div
        className="flex items-center justify-center h-14 border-b"
        style={{ borderColor: "var(--border)" }}
      >
        <span
          className="text-lg font-bold"
          style={{ color: "var(--accent-blue)" }}
        >
          {expanded ? "SmallCap" : "SC"}
        </span>
      </div>

      {/* Nav items */}
      <nav className="flex-1 py-3 px-2 space-y-1">
        {navItems.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-3 rounded-md px-2.5 py-2.5 transition-colors relative group"
              style={{
                backgroundColor: isActive
                  ? "rgba(59, 130, 246, 0.15)"
                  : "transparent",
                color: isActive
                  ? "var(--accent-blue)"
                  : "var(--text-secondary)",
              }}
              title={!expanded ? item.label : undefined}
            >
              {isActive && (
                <span
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-r"
                  style={{ backgroundColor: "var(--accent-blue)" }}
                />
              )}
              <span className="flex-shrink-0">{item.icon}</span>
              {expanded && (
                <span className="text-sm font-medium whitespace-nowrap">
                  {item.label}
                </span>
              )}
              {/* Tooltip when collapsed */}
              {!expanded && (
                <span
                  className="absolute left-full ml-2 px-2 py-1 rounded text-xs font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50"
                  style={{
                    backgroundColor: "var(--bg-hover)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {item.label}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-center h-10 border-t transition-colors"
        style={{
          borderColor: "var(--border)",
          color: "var(--text-muted)",
        }}
      >
        {expanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
      </button>
    </aside>
  );
}

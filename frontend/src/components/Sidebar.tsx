"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  label: string;
  icon: string; // emoji placeholder, swap for icons later
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", icon: "\u{1F4CA}" },
  { href: "/analysis", label: "Analysis", icon: "\u{1F50D}" },
  { href: "/divergence", label: "Divergence", icon: "\u{1F500}" },
  { href: "/backtest", label: "Backtest", icon: "\u{23F1}" },
  { href: "/portfolio", label: "Portfolio", icon: "\u{1F4BC}" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-60 flex-col border-r border-gray-800 bg-gray-950 text-gray-300">
      {/* Brand */}
      <div className="flex items-center gap-2 px-5 py-6">
        <span className="text-xl font-bold tracking-tight text-white">
          TradingAgents
        </span>
      </div>

      {/* Nav links */}
      <nav className="flex-1 space-y-1 px-3">
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-brand-700/20 text-brand-400"
                  : "hover:bg-gray-800 hover:text-white"
              }`}
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-gray-800 px-5 py-4 text-xs text-gray-600">
        v0.1.0
      </div>
    </aside>
  );
}

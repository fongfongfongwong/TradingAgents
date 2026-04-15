"use client";

import { useState, type FormEvent } from "react";
import { useTicker } from "@/hooks/useTicker";

export default function CommandBar() {
  const { ticker, setTicker, addToWatchlist } = useTicker();
  const [input, setInput] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (!t) return;
    setTicker(t);
    addToWatchlist(t);
    setInput("");
  };

  return (
    <header className="flex h-11 shrink-0 items-center gap-4 border-b border-white/[0.08] bg-[#0f1011] px-4">
      {/* Brand */}
      <span className="text-sm font-semibold tracking-tight text-[#d0d6e0]">
        FLAB MASA
      </span>

      <div className="h-4 w-px bg-white/[0.08]" />

      {/* Active ticker badge */}
      <span className="rounded bg-[#5e6ad2]/20 px-2 py-0.5 text-xs font-bold text-[#828fff]">
        {ticker}
      </span>

      {/* Search / command input */}
      <form onSubmit={handleSubmit} className="flex-1">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type ticker and press Enter..."
          className="w-full max-w-xs rounded border border-white/[0.08] bg-white/[0.02] px-3 py-1 text-xs text-[#f7f8f8] placeholder-[#62666d] outline-none focus:border-[#5e6ad2]/50"
        />
      </form>

      {/* Right side: indicators */}
      <div className="flex items-center gap-3 text-xs text-[#8a8f98]">
        <span className="rounded bg-white/[0.03] px-2 py-0.5">GPT-5.4</span>
        <span className="rounded bg-white/[0.03] px-2 py-0.5">yfinance</span>
      </div>
    </header>
  );
}

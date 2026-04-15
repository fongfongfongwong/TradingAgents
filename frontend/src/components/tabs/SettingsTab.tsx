"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  getCostsToday,
  getRuntimeConfig,
  updateRuntimeConfig,
  type CostsToday,
  type LlmProvider,
  type MacroVendor,
  type NewsVendor,
  type OptionsVendor,
  type OutputLanguage,
  type PriceVendor,
  type RuntimeConfig,
  type SocialVendor,
} from "@/lib/api";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface ApiKeySlot {
  id: string;
  label: string;
  category: string;
  tier: string;
  url: string;
  configured: string;
  masked_value: string;
}

interface ApiKeyHealth {
  key_id: string;
  label: string;
  status: "ok" | "fail" | "error" | "skip";
  detail: string;
  wired: boolean;
  wire_note: string;
}

interface TestKeysResponse {
  tested: number;
  ok: number;
  failed: number;
  results: ApiKeyHealth[];
}

/* ------------------------------------------------------------------ */
/*  Runtime config static lists                                        */
/* ------------------------------------------------------------------ */

const ANTHROPIC_MODELS: ReadonlyArray<{ id: string; label: string }> = [
  { id: "claude-opus-4-1-20250805", label: "Claude Opus 4.1" },
  { id: "claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
];

const PROVIDERS: ReadonlyArray<{ id: LlmProvider; label: string; disabled: boolean }> = [
  { id: "anthropic", label: "Anthropic", disabled: false },
  { id: "openai", label: "OpenAI (Coming soon)", disabled: true },
  { id: "google", label: "Google (Coming soon)", disabled: true },
  { id: "xai", label: "xAI (Coming soon)", disabled: true },
];

const PRICE_VENDORS: ReadonlyArray<{ id: PriceVendor; label: string }> = [
  { id: "yfinance", label: "Yahoo Finance" },
  { id: "polygon", label: "Polygon.io" },
  { id: "alpha_vantage", label: "Alpha Vantage" },
];
const NEWS_VENDORS: ReadonlyArray<{ id: NewsVendor; label: string }> = [
  { id: "yfinance", label: "Yahoo Finance" },
  { id: "finnhub", label: "Finnhub" },
];
const OPTIONS_VENDORS: ReadonlyArray<{ id: OptionsVendor; label: string }> = [
  { id: "yfinance", label: "Yahoo Finance" },
  { id: "cboe", label: "CBOE" },
];
const MACRO_VENDORS: ReadonlyArray<{ id: MacroVendor; label: string }> = [
  { id: "yfinance", label: "Yahoo Finance" },
  { id: "fred", label: "FRED" },
];
const SOCIAL_VENDORS: ReadonlyArray<{ id: SocialVendor; label: string }> = [
  { id: "disabled", label: "Disabled" },
  { id: "fear_greed_apewisdom", label: "Fear & Greed + Apewisdom" },
];
const LANGUAGES: ReadonlyArray<{ id: OutputLanguage; label: string }> = [
  { id: "en", label: "English" },
  { id: "zh", label: "Chinese" },
  { id: "ja", label: "Japanese" },
  { id: "es", label: "Spanish" },
];

const ANALYSTS: ReadonlyArray<string> = [
  "market",
  "news",
  "fundamentals",
  "macro",
  "options",
  "social",
];

/* ------------------------------------------------------------------ */
/*  Shared styles                                                      */
/* ------------------------------------------------------------------ */

const inputClass =
  "w-full rounded border border-white/[0.08] bg-white/[0.02] px-2 py-1 text-[11px] text-[#f7f8f8] outline-none focus:border-[#5e6ad2]/50";
const labelClass = "mb-1 block text-[10px] font-medium text-[#8a8f98]";
const sectionHeader =
  "mb-3 text-xs font-semibold uppercase tracking-wider text-[#8a8f98]";

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function SettingsTab() {
  // API keys state
  const [keys, setKeys] = useState<ApiKeySlot[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Live API health state
  const [health, setHealth] = useState<Record<string, ApiKeyHealth>>({});
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthLastRun, setHealthLastRun] = useState<number | null>(null);

  const runHealthCheck = async () => {
    setHealthLoading(true);
    try {
      const resp = await fetch(`${BASE_URL}/api/config/test-keys`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: TestKeysResponse = await resp.json();
      const map: Record<string, ApiKeyHealth> = {};
      for (const r of data.results) map[r.key_id] = r;
      setHealth(map);
      setHealthLastRun(Date.now());
    } catch {
      setMessage("Health check failed. Is the backend running?");
    } finally {
      setHealthLoading(false);
    }
  };

  // Runtime config state
  const [runtime, setRuntime] = useState<RuntimeConfig | null>(null);
  const [runtimeInitial, setRuntimeInitial] = useState<RuntimeConfig | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [runtimeSaving, setRuntimeSaving] = useState(false);
  const [runtimeMessage, setRuntimeMessage] = useState<string | null>(null);

  // Cost dashboard state
  const [costs, setCosts] = useState<CostsToday | null>(null);

  const refreshCosts = () => {
    getCostsToday()
      .then((data) => setCosts(data))
      .catch(() => {
        // Silent — leave previous data in place on failure.
      });
  };

  useEffect(() => {
    fetch(`${BASE_URL}/api/config/api-keys`)
      .then((r) => r.json())
      .then((data: ApiKeySlot[]) => {
        setKeys(data);
        setLoading(false);
        // Kick off initial health probe once the key list is known
        runHealthCheck();
      })
      .catch(() => setLoading(false));

    getRuntimeConfig()
      .then((cfg) => {
        setRuntime(cfg);
        setRuntimeInitial(cfg);
      })
      .catch(() => {
        setRuntimeMessage("Failed to load runtime config. Is the backend running?");
      })
      .finally(() => setRuntimeLoading(false));

    // Initial cost fetch + 30s polling
    refreshCosts();
    const costsInterval = window.setInterval(refreshCosts, 30_000);
    return () => {
      window.clearInterval(costsInterval);
    };
  }, []);

  const handleChange = (id: string, val: string) => {
    setValues((prev) => ({ ...prev, [id]: val }));
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    const toSend: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) {
      if (v.trim()) toSend[k] = v.trim();
    }
    if (Object.keys(toSend).length === 0) {
      setMessage("No keys to save.");
      return;
    }

    setSaving(true);
    setMessage(null);
    try {
      const resp = await fetch(`${BASE_URL}/api/config/api-keys`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toSend),
      });
      const data = await resp.json();
      setMessage(`Saved ${data.count} API key(s). Changes take effect immediately.`);
      setValues({});
      const refreshed = await fetch(`${BASE_URL}/api/config/api-keys`).then((r) =>
        r.json(),
      );
      setKeys(refreshed);
    } catch {
      setMessage("Failed to save. Is the backend running?");
    } finally {
      setSaving(false);
    }
  };

  /* ---- Runtime config helpers ---- */

  const runtimeDirty =
    runtime !== null &&
    runtimeInitial !== null &&
    JSON.stringify(runtime) !== JSON.stringify(runtimeInitial);

  const updateRuntime = <K extends keyof RuntimeConfig>(
    key: K,
    value: RuntimeConfig[K],
  ) => {
    setRuntime((prev) => (prev === null ? prev : { ...prev, [key]: value }));
  };

  const toggleAnalyst = (analyst: string) => {
    if (runtime === null) return;
    const has = runtime.analyst_selection.includes(analyst);
    const next = has
      ? runtime.analyst_selection.filter((a) => a !== analyst)
      : [...runtime.analyst_selection, analyst];
    updateRuntime("analyst_selection", next);
  };

  const handleRuntimeSave = async (e: FormEvent) => {
    e.preventDefault();
    if (runtime === null) return;
    setRuntimeSaving(true);
    setRuntimeMessage(null);
    try {
      const updated = await updateRuntimeConfig(runtime);
      setRuntime(updated);
      setRuntimeInitial(updated);
      setRuntimeMessage("Runtime configuration saved.");
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Save failed";
      setRuntimeMessage(`Failed: ${detail.length > 100 ? detail.slice(0, 100) + "..." : detail}`);
    } finally {
      setRuntimeSaving(false);
    }
  };

  // Group API keys by category
  const categories = keys.reduce<Record<string, ApiKeySlot[]>>((acc, k) => {
    if (!acc[k.category]) acc[k.category] = [];
    acc[k.category].push(k);
    return acc;
  }, {});

  if (loading) {
    return <p className="text-xs text-[#8a8f98]">Loading configuration...</p>;
  }

  return (
    <div className="space-y-8">
      {/* -------- API KEYS -------- */}
      <div>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">API Configuration</h2>
          <div className="flex items-center gap-3">
            {healthLastRun && (
              <span className="text-[10px] text-[#62666d]">
                Last checked {Math.max(0, Math.round((Date.now() - healthLastRun) / 1000))}s ago
              </span>
            )}
            <button
              type="button"
              onClick={runHealthCheck}
              disabled={healthLoading}
              className="rounded border border-white/[0.08] bg-white/[0.02] px-3 py-1 text-[11px] font-medium text-[#d0d6e0] transition-colors hover:border-[#5e6ad2]/50 hover:text-white disabled:opacity-40"
            >
              {healthLoading ? "Testing…" : "Test Keys"}
            </button>
          </div>
        </div>
        <p className="mt-1 text-[11px] text-[#8a8f98]">
          Enter your API keys below. Keys persist in the SQLite key store and
          take effect immediately. The status dot next to each key reflects a
          live upstream probe: <span className="text-[#10b981]">●</span> ok,{" "}
          <span className="text-[#e23b4a]">●</span> failing,{" "}
          <span className="text-[#f59e0b]">●</span> untested,{" "}
          <span className="text-[#62666d]">●</span> not configured.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {Object.entries(categories).map(([category, slots]) => (
          <div key={category}>
            <h3 className={sectionHeader}>{category}</h3>
            <div className="space-y-2">
              {slots.map((slot) => {
                const h = health[slot.id];
                const isConfigured = slot.configured === "true";
                let dotColor = "bg-[#62666d]";
                let dotShadow = "";
                let statusTitle = "Not configured";
                if (isConfigured) {
                  if (!h) {
                    dotColor = "bg-[#f59e0b]";
                    statusTitle = "Configured — not yet tested";
                  } else if (h.status === "ok") {
                    dotColor = "bg-[#10b981]";
                    dotShadow = "shadow-[0_0_6px_rgba(16,185,129,0.6)]";
                    statusTitle = `OK — ${h.detail}${h.wired ? " · WIRED: " + h.wire_note : " · not wired to v3 pipeline"}`;
                  } else if (h.status === "fail" || h.status === "error") {
                    dotColor = "bg-[#e23b4a]";
                    dotShadow = "shadow-[0_0_6px_rgba(226,59,74,0.7)] animate-pulse";
                    statusTitle = `FAILING: ${h.detail}`;
                  } else {
                    dotColor = "bg-[#f59e0b]";
                    statusTitle = `SKIP: ${h.detail}`;
                  }
                }
                return (
                <div
                  key={slot.id}
                  className="flex items-center gap-3 rounded border border-white/[0.08] bg-[#0f1011] px-3 py-2"
                  title={statusTitle}
                >
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${dotColor} ${dotShadow}`}
                  />
                  <div className="w-44 shrink-0">
                    <a
                      href={slot.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs font-medium text-[#d0d6e0] hover:text-[#5e6ad2] hover:underline"
                    >
                      {slot.label}
                    </a>
                    <span className="ml-2 text-[9px] text-[#62666d]">
                      {slot.tier}
                    </span>
                  </div>
                  {slot.configured === "true" && !values[slot.id] ? (
                    <span className="font-mono text-[10px] text-[#10b981]">
                      {slot.masked_value || "configured"}
                    </span>
                  ) : null}
                  <input
                    type="password"
                    placeholder={
                      slot.configured === "true"
                        ? "Replace key..."
                        : "Paste API key..."
                    }
                    value={values[slot.id] ?? ""}
                    onChange={(e) => handleChange(slot.id, e.target.value)}
                    className="flex-1 rounded border border-white/[0.08] bg-white/[0.02] px-2 py-1 font-mono text-[11px] text-[#f7f8f8] placeholder-[#62666d] outline-none focus:border-[#5e6ad2]/50"
                  />
                  <span className="hidden font-mono text-[9px] text-[#62666d] lg:inline">
                    {slot.id}
                  </span>
                </div>
                );
              })}
            </div>
          </div>
        ))}

        <div className="flex items-center gap-4">
          <button
            type="submit"
            disabled={saving || Object.values(values).every((v) => !v.trim())}
            className="rounded bg-[#5e6ad2] px-6 py-2 text-xs font-medium text-white transition-colors hover:bg-[#7170ff] disabled:opacity-40"
          >
            {saving ? "Saving..." : "Save API Keys"}
          </button>
          {message && (
            <span
              className={`text-xs ${
                message.includes("Failed")
                  ? "text-[#e23b4a]"
                  : "text-[#10b981]"
              }`}
            >
              {message}
            </span>
          )}
        </div>
      </form>

      {/* -------- COST DASHBOARD -------- */}
      <div className="mb-6 rounded border border-white/[0.08] bg-[#0f1011] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#d0d6e0]">Today&apos;s LLM Spend</h3>
          <button
            type="button"
            onClick={refreshCosts}
            className="text-[10px] text-[#8a8f98] hover:text-white"
          >
            Refresh
          </button>
        </div>
        {costs ? (
          <>
            <div className="mb-3 flex items-baseline gap-3">
              <span className="font-mono text-2xl font-bold text-[#f7f8f8]">
                ${costs.total_usd.toFixed(2)}
              </span>
              <span className="text-[11px] text-[#8a8f98]">
                of ${costs.budget_daily_usd.toFixed(2)} (
                {costs.pct_of_daily_budget.toFixed(1)}%)
              </span>
            </div>
            {/* Progress bar */}
            <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-white/[0.05]">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(100, costs.pct_of_daily_budget)}%`,
                  backgroundColor:
                    costs.pct_of_daily_budget > 80
                      ? "#e23b4a"
                      : costs.pct_of_daily_budget > 50
                        ? "#f59e0b"
                        : "#10b981",
                }}
              />
            </div>
            {/* Breakdown grid */}
            <div className="grid grid-cols-3 gap-3 text-[10px]">
              <div>
                <div className="mb-1 text-[9px] font-semibold uppercase text-[#62666d]">
                  By Agent
                </div>
                {Object.entries(costs.by_agent)
                  .slice(0, 4)
                  .map(([k, v]) => (
                    <div key={k} className="flex justify-between text-[#8a8f98]">
                      <span>{k}</span>
                      <span className="font-mono text-[#d0d6e0]">${v.toFixed(2)}</span>
                    </div>
                  ))}
              </div>
              <div>
                <div className="mb-1 text-[9px] font-semibold uppercase text-[#62666d]">
                  Top Tickers
                </div>
                {Object.entries(costs.by_ticker)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 4)
                  .map(([k, v]) => (
                    <div key={k} className="flex justify-between text-[#8a8f98]">
                      <span>{k}</span>
                      <span className="font-mono text-[#d0d6e0]">${v.toFixed(2)}</span>
                    </div>
                  ))}
              </div>
              <div>
                <div className="mb-1 text-[9px] font-semibold uppercase text-[#62666d]">
                  Stats
                </div>
                <div className="text-[#8a8f98]">
                  Calls:{" "}
                  <span className="font-mono text-[#d0d6e0]">{costs.call_count}</span>
                </div>
                {costs.budget_breached && (
                  <div className="mt-1 text-[#e23b4a]">Budget breached</div>
                )}
              </div>
            </div>
          </>
        ) : (
          <p className="text-[11px] text-[#62666d]">Loading cost data...</p>
        )}
      </div>

      {/* -------- RUNTIME CONFIGURATION -------- */}
      <div className="border-t border-white/[0.08] pt-6">
        <h2 className="text-lg font-bold">
          Runtime Configuration
          {runtimeDirty && (
            <span className="ml-2 text-[#f59e0b]" title="Unsaved changes">
              *
            </span>
          )}
        </h2>
        <p className="mt-1 text-[11px] text-[#8a8f98]">
          Choose models, data vendors, budgets, and analyst mix. Saves to disk
          and takes effect on the next pipeline run.
        </p>
      </div>

      {runtimeLoading || runtime === null ? (
        <p className="text-xs text-[#8a8f98]">Loading runtime configuration...</p>
      ) : (
        <form onSubmit={handleRuntimeSave} className="space-y-6">
          {/* LLM MODELS */}
          <div>
            <h3 className={sectionHeader}>LLM Models</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div>
                <label className={labelClass}>Provider</label>
                <select
                  value={runtime.llm_provider}
                  onChange={(e) =>
                    updateRuntime("llm_provider", e.target.value as LlmProvider)
                  }
                  className={inputClass}
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.id} value={p.id} disabled={p.disabled}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Thesis Model</label>
                <select
                  value={runtime.thesis_model}
                  onChange={(e) => updateRuntime("thesis_model", e.target.value)}
                  className={inputClass}
                >
                  {ANTHROPIC_MODELS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Antithesis Model</label>
                <select
                  value={runtime.antithesis_model}
                  onChange={(e) =>
                    updateRuntime("antithesis_model", e.target.value)
                  }
                  className={inputClass}
                >
                  {ANTHROPIC_MODELS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Base Rate Model</label>
                <select
                  value={runtime.base_rate_model}
                  onChange={(e) =>
                    updateRuntime("base_rate_model", e.target.value)
                  }
                  className={inputClass}
                >
                  {ANTHROPIC_MODELS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Synthesis Model</label>
                <select
                  value={runtime.synthesis_model}
                  onChange={(e) =>
                    updateRuntime("synthesis_model", e.target.value)
                  }
                  className={inputClass}
                >
                  {ANTHROPIC_MODELS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Synthesis Fallback Model</label>
                <select
                  value={runtime.synthesis_fallback_model}
                  onChange={(e) =>
                    updateRuntime("synthesis_fallback_model", e.target.value)
                  }
                  className={inputClass}
                >
                  {ANTHROPIC_MODELS.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* DATA VENDORS */}
          <div>
            <h3 className={sectionHeader}>Data Vendors</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div>
                <label className={labelClass}>Price</label>
                <select
                  value={runtime.data_vendor_price}
                  onChange={(e) =>
                    updateRuntime(
                      "data_vendor_price",
                      e.target.value as PriceVendor,
                    )
                  }
                  className={inputClass}
                >
                  {PRICE_VENDORS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>News</label>
                <select
                  value={runtime.data_vendor_news}
                  onChange={(e) =>
                    updateRuntime(
                      "data_vendor_news",
                      e.target.value as NewsVendor,
                    )
                  }
                  className={inputClass}
                >
                  {NEWS_VENDORS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Options</label>
                <select
                  value={runtime.data_vendor_options}
                  onChange={(e) =>
                    updateRuntime(
                      "data_vendor_options",
                      e.target.value as OptionsVendor,
                    )
                  }
                  className={inputClass}
                >
                  {OPTIONS_VENDORS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Macro</label>
                <select
                  value={runtime.data_vendor_macro}
                  onChange={(e) =>
                    updateRuntime(
                      "data_vendor_macro",
                      e.target.value as MacroVendor,
                    )
                  }
                  className={inputClass}
                >
                  {MACRO_VENDORS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelClass}>Social</label>
                <select
                  value={runtime.data_vendor_social}
                  onChange={(e) =>
                    updateRuntime(
                      "data_vendor_social",
                      e.target.value as SocialVendor,
                    )
                  }
                  className={inputClass}
                >
                  {SOCIAL_VENDORS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* BUDGET & OUTPUT */}
          <div>
            <h3 className={sectionHeader}>Budget &amp; Output</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label className={labelClass}>Daily Budget (USD)</label>
                <input
                  type="number"
                  min={0}
                  max={10000}
                  step={0.5}
                  value={runtime.budget_daily_usd}
                  onChange={(e) =>
                    updateRuntime(
                      "budget_daily_usd",
                      Number(e.target.value) || 0,
                    )
                  }
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Per-Ticker Budget (USD)</label>
                <input
                  type="number"
                  min={0}
                  max={1000}
                  step={0.1}
                  value={runtime.budget_per_ticker_usd}
                  onChange={(e) =>
                    updateRuntime(
                      "budget_per_ticker_usd",
                      Number(e.target.value) || 0,
                    )
                  }
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Output Language</label>
                <select
                  value={runtime.output_language}
                  onChange={(e) =>
                    updateRuntime(
                      "output_language",
                      e.target.value as OutputLanguage,
                    )
                  }
                  className={inputClass}
                >
                  {LANGUAGES.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* ANALYSTS */}
          <div>
            <h3 className={sectionHeader}>Analysts</h3>
            <div className="flex flex-wrap gap-3">
              {ANALYSTS.map((analyst) => {
                const checked = runtime.analyst_selection.includes(analyst);
                return (
                  <label
                    key={analyst}
                    className="flex items-center gap-2 rounded border border-white/[0.08] bg-[#0f1011] px-3 py-1.5 text-[11px] text-[#d0d6e0]"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleAnalyst(analyst)}
                      className="h-3 w-3 accent-[#5e6ad2]"
                    />
                    <span className="capitalize">{analyst}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="flex items-center gap-4">
            <button
              type="submit"
              disabled={runtimeSaving || !runtimeDirty}
              className="rounded bg-[#5e6ad2] px-6 py-2 text-xs font-medium text-white transition-colors hover:bg-[#7170ff] disabled:opacity-40"
            >
              {runtimeSaving ? "Saving..." : "Save Runtime Config"}
            </button>
            {runtimeMessage && (
              <span
                className={`text-xs ${
                  runtimeMessage.startsWith("Failed")
                    ? "text-[#e23b4a]"
                    : "text-[#10b981]"
                }`}
              >
                {runtimeMessage}
              </span>
            )}
          </div>
        </form>
      )}

      {/* Data source status summary */}
      <div className="rounded border border-white/[0.08] bg-[#0f1011] p-4">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#8a8f98]">
          Data Source Status
        </h3>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          {keys.map((k) => (
            <div
              key={k.id}
              className={`rounded border px-2 py-1.5 text-center text-[10px] ${
                k.configured === "true"
                  ? "border-[#10b981]/30 bg-[#10b981]/10 text-[#10b981]"
                  : "border-white/[0.05] bg-white/[0.02] text-[#62666d]"
              }`}
            >
              {k.label}
            </div>
          ))}
        </div>
        <p className="mt-2 text-[9px] text-[#62666d]">
          Green = live data. Gray = mock data (realistic but not real-time).
        </p>
      </div>
    </div>
  );
}

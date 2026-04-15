"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getSourcesStatus,
  getSourceHistory,
  getSourceCoverage,
  probeSource,
  type SourceProbeResult,
  type SourceCoverage,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type SortKey =
  | "connector_name"
  | "status"
  | "latency_ms"
  | "freshness_seconds"
  | "completeness_pct"
  | "rate_limit_pct"
  | "health_score"
  | "tier";

export type SortDir = "asc" | "desc";

export type ViewMode = "table" | "compare" | "coverage";

export interface SourceHistoryMap {
  [connectorName: string]: SourceProbeResult[];
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function sortProbes(
  items: SourceProbeResult[],
  key: SortKey,
  dir: SortDir,
): SourceProbeResult[] {
  const sorted = [...items].sort((a, b) => {
    const av = a[key] ?? -Infinity;
    const bv = b[key] ?? -Infinity;
    if (av < bv) return -1;
    if (av > bv) return 1;
    return 0;
  });
  return dir === "desc" ? sorted.reverse() : sorted;
}

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

const POLL_INTERVAL = 60_000;
const HISTORY_BATCH_SIZE = 5; // fetch N histories at a time to avoid burst

export function useSourceMonitor() {
  /* -- Core state --------------------------------------------------- */
  const [sources, setSources] = useState<SourceProbeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);

  /* -- View / filter state ------------------------------------------ */
  const [selected, setSelected] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("health_score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [compareSet, setCompareSet] = useState<Set<string>>(new Set());

  /* -- History cache ------------------------------------------------ */
  const [histories, setHistories] = useState<SourceHistoryMap>({});
  const historiesFetchedRef = useRef<Set<string>>(new Set());

  /* -- Coverage cache ----------------------------------------------- */
  const [coverage, setCoverage] = useState<SourceCoverage | null>(null);

  /* ================================================================ */
  /*  Data fetching                                                    */
  /* ================================================================ */

  const fetchSources = useCallback((force = false) => {
    setLoading(true);
    setError(null);
    getSourcesStatus(force)
      .then((data) => {
        setSources(data);
        setLastFetched(new Date().toISOString());
      })
      .catch(() => setError("Failed to fetch source status. Is the backend running?"))
      .finally(() => setLoading(false));
  }, []);

  // Initial fetch + polling
  useEffect(() => {
    fetchSources();
    const interval = setInterval(() => fetchSources(), POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchSources]);

  /* -- History prefetch --------------------------------------------- */

  // When sources arrive, prefetch histories for those we haven't fetched yet.
  // Batched to avoid hammering the server.
  useEffect(() => {
    const unfetched = sources
      .map((s) => s.connector_name)
      .filter((n) => !historiesFetchedRef.current.has(n));

    if (unfetched.length === 0) return;

    let cancelled = false;

    (async () => {
      for (let i = 0; i < unfetched.length; i += HISTORY_BATCH_SIZE) {
        if (cancelled) break;
        const batch = unfetched.slice(i, i + HISTORY_BATCH_SIZE);
        const results = await Promise.allSettled(
          batch.map((name) => getSourceHistory(name, 30)),
        );

        if (cancelled) break;

        setHistories((prev) => {
          const next = { ...prev };
          batch.forEach((name, idx) => {
            const r = results[idx];
            if (r.status === "fulfilled") {
              next[name] = r.value;
            }
            historiesFetchedRef.current.add(name);
          });
          return next;
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sources]);

  /* -- Coverage fetch ----------------------------------------------- */

  useEffect(() => {
    if (viewMode !== "coverage") return;
    if (coverage !== null) return; // already fetched

    getSourceCoverage()
      .then(setCoverage)
      .catch((err) => {
        console.error("Failed to fetch source coverage:", err);
      });
  }, [viewMode, coverage]);

  /* ================================================================ */
  /*  Actions                                                          */
  /* ================================================================ */

  const handleProbeAll = useCallback(() => {
    setProbing("__all__");
    getSourcesStatus(true)
      .then((data) => {
        setSources(data);
        setLastFetched(new Date().toISOString());
        // Invalidate histories so they get refetched
        historiesFetchedRef.current.clear();
      })
      .catch((err) => {
        console.error("Probe all sources failed:", err);
      })
      .finally(() => setProbing(null));
  }, []);

  const handleProbeOne = useCallback((name: string) => {
    setProbing(name);
    probeSource(name)
      .then((result) => {
        setSources((prev) => {
          const idx = prev.findIndex((s) => s.connector_name === result.connector_name);
          if (idx === -1) return [...prev, result];
          const next = [...prev];
          next[idx] = result;
          return next;
        });
        setLastFetched(new Date().toISOString());
        // Refresh history for this connector
        historiesFetchedRef.current.delete(name);
        getSourceHistory(name, 30)
          .then((h) => {
            setHistories((prev) => ({ ...prev, [name]: h }));
            historiesFetchedRef.current.add(name);
          })
          .catch((err) => {
            console.error(`History refresh failed for ${name}:`, err);
          });
      })
      .catch((err) => {
        console.error(`Probe failed for ${name}:`, err);
      })
      .finally(() => setProbing(null));
  }, []);

  const handleSort = useCallback(
    (key: SortKey) => {
      if (key === sortKey) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir(key === "connector_name" ? "asc" : "desc");
      }
    },
    [sortKey],
  );

  const toggleCompare = useCallback((name: string) => {
    setCompareSet((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else if (next.size < 6) next.add(name);
      return next;
    });
  }, []);

  /* ================================================================ */
  /*  Derived data                                                     */
  /* ================================================================ */

  const filtered = useMemo(() => {
    let list = sources;
    if (categoryFilter) {
      list = list.filter((s) => s.categories.includes(categoryFilter));
    }
    if (statusFilter) {
      list = list.filter((s) => s.status === statusFilter);
    }
    return list;
  }, [sources, categoryFilter, statusFilter]);

  const sorted = useMemo(
    () => sortProbes(filtered, sortKey, sortDir),
    [filtered, sortKey, sortDir],
  );

  const selectedSource = sources.find((s) => s.connector_name === selected) ?? null;
  const compareSources = sources.filter((s) => compareSet.has(s.connector_name));

  // Aggregate stats
  const stats = useMemo(() => {
    const ok = sources.filter((s) => s.status === "ok").length;
    const warn = sources.filter((s) => s.status === "warn").length;
    const err = sources.filter((s) => s.status === "err").length;
    const reachable = sources.filter((s) => s.reachable);
    const avgHealth =
      sources.length > 0
        ? sources.reduce((a, s) => a + s.health_score, 0) / sources.length
        : 0;
    const avgLatency =
      reachable.length > 0
        ? reachable.reduce((a, s) => a + s.latency_ms, 0) / reachable.length
        : 0;
    const avgCompleteness =
      sources.length > 0
        ? sources.reduce((a, s) => a + s.completeness_pct, 0) / sources.length
        : 0;
    return { ok, warn, err, avgHealth, avgLatency, avgCompleteness, total: sources.length };
  }, [sources]);

  // Category distribution
  const categoryStats = useMemo(() => {
    const map: Record<string, { total: number; ok: number; err: number }> = {};
    for (const src of sources) {
      for (const cat of src.categories) {
        if (!map[cat]) map[cat] = { total: 0, ok: 0, err: 0 };
        map[cat].total += 1;
        if (src.status === "ok") map[cat].ok += 1;
        if (src.status === "err") map[cat].err += 1;
      }
    }
    return map;
  }, [sources]);

  return {
    // Core data
    sources,
    sorted,
    filtered,
    loading,
    error,
    lastFetched,
    probing,
    histories,
    coverage,
    stats,
    categoryStats,

    // Selection / view
    selected,
    setSelected,
    selectedSource,
    compareSources,
    compareSet,

    // View / filter
    sortKey,
    sortDir,
    categoryFilter,
    setCategoryFilter,
    statusFilter,
    setStatusFilter,
    viewMode,
    setViewMode,

    // Actions
    fetchSources,
    handleProbeAll,
    handleProbeOne,
    handleSort,
    toggleCompare,
  };
}

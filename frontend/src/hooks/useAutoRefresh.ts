import { useCallback, useEffect, useRef, useState } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface UseAutoRefreshOptions {
  /** Interval between refreshes in milliseconds. Defaults to 30 minutes. */
  intervalMs?: number;
  /** Whether auto-refresh is initially enabled. */
  enabled?: boolean;
  /** Callback invoked on each refresh cycle. */
  onRefresh: () => void;
}

export interface UseAutoRefreshReturn {
  /** Milliseconds until the next scheduled refresh. */
  nextRefreshIn: number;
  /** Whether auto-refresh is currently active. */
  isEnabled: boolean;
  /** Toggle auto-refresh on/off. */
  toggle: () => void;
  /** Trigger an immediate refresh and reset the countdown. */
  refreshNow: () => void;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const DEFAULT_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes
const COUNTDOWN_TICK_MS = 1_000;

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

export function useAutoRefresh(
  options: UseAutoRefreshOptions,
): UseAutoRefreshReturn {
  const {
    intervalMs = DEFAULT_INTERVAL_MS,
    enabled: initialEnabled = true,
    onRefresh,
  } = options;

  const [isEnabled, setIsEnabled] = useState(initialEnabled);
  const [nextRefreshIn, setNextRefreshIn] = useState(intervalMs);

  // Keep a stable ref to onRefresh so interval closures always see the
  // latest callback without restarting timers on every render.
  const onRefreshRef = useRef(onRefresh);
  onRefreshRef.current = onRefresh;

  // Track whether the document is visible. When the laptop lid is closed
  // (or the tab is backgrounded) we pause the refresh cycle.
  const visibleRef = useRef(true);

  // Refs for the two intervals so we can clear them deterministically.
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ---- helpers ---- */

  const clearTimers = useCallback(() => {
    if (refreshTimerRef.current !== null) {
      clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    if (countdownTimerRef.current !== null) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
  }, []);

  const startTimers = useCallback(() => {
    clearTimers();

    setNextRefreshIn(intervalMs);

    // Main refresh interval.
    refreshTimerRef.current = setInterval(() => {
      if (visibleRef.current) {
        onRefreshRef.current();
        setNextRefreshIn(intervalMs);
      }
    }, intervalMs);

    // 1-second countdown ticker.
    countdownTimerRef.current = setInterval(() => {
      if (visibleRef.current) {
        setNextRefreshIn((prev) => Math.max(0, prev - COUNTDOWN_TICK_MS));
      }
    }, COUNTDOWN_TICK_MS);
  }, [intervalMs, clearTimers]);

  /* ---- visibility handling ---- */

  useEffect(() => {
    const handleVisibility = () => {
      const hidden = document.hidden;
      visibleRef.current = !hidden;

      if (hidden) {
        // Pause — clear timers so no background work runs.
        clearTimers();
      } else if (isEnabled) {
        // Resume — restart with a fresh cycle.
        startTimers();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [isEnabled, clearTimers, startTimers]);

  /* ---- start / stop based on isEnabled ---- */

  useEffect(() => {
    if (isEnabled) {
      startTimers();
    } else {
      clearTimers();
    }

    return clearTimers;
  }, [isEnabled, startTimers, clearTimers]);

  /* ---- public API ---- */

  const toggle = useCallback(() => {
    setIsEnabled((prev) => !prev);
  }, []);

  const refreshNow = useCallback(() => {
    onRefreshRef.current();
    if (isEnabled) {
      startTimers();
    }
  }, [isEnabled, startTimers]);

  return { nextRefreshIn, isEnabled, toggle, refreshNow };
}

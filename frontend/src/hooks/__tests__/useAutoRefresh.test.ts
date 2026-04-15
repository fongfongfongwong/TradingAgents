import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { useAutoRefresh } from "../useAutoRefresh";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/**
 * Stub `document.hidden` and fire the `visibilitychange` event.
 */
function setDocumentHidden(hidden: boolean): void {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("useAutoRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Ensure document starts as visible.
    setDocumentHidden(false);
  });

  afterEach(() => {
    vi.useRealTimers();
    // Restore visibility.
    setDocumentHidden(false);
  });

  it("calls onRefresh after intervalMs elapses", () => {
    const onRefresh = vi.fn();
    const intervalMs = 5_000;

    renderHook(() =>
      useAutoRefresh({ intervalMs, enabled: true, onRefresh }),
    );

    expect(onRefresh).not.toHaveBeenCalled();

    // Advance just under the interval -- should NOT have fired.
    act(() => { vi.advanceTimersByTime(4_999); });
    expect(onRefresh).not.toHaveBeenCalled();

    // Advance past the interval.
    act(() => { vi.advanceTimersByTime(1); });
    expect(onRefresh).toHaveBeenCalledTimes(1);

    // Another full interval.
    act(() => { vi.advanceTimersByTime(intervalMs); });
    expect(onRefresh).toHaveBeenCalledTimes(2);
  });

  it("toggle() stops and restarts the interval", () => {
    const onRefresh = vi.fn();
    const intervalMs = 5_000;

    const { result } = renderHook(() =>
      useAutoRefresh({ intervalMs, enabled: true, onRefresh }),
    );

    expect(result.current.isEnabled).toBe(true);

    // Toggle OFF.
    act(() => { result.current.toggle(); });
    expect(result.current.isEnabled).toBe(false);

    // Advance time -- should NOT fire.
    act(() => { vi.advanceTimersByTime(intervalMs * 3); });
    expect(onRefresh).not.toHaveBeenCalled();

    // Toggle back ON.
    act(() => { result.current.toggle(); });
    expect(result.current.isEnabled).toBe(true);

    // Now it should fire after one full interval.
    act(() => { vi.advanceTimersByTime(intervalMs); });
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("refreshNow() calls onRefresh immediately and resets the timer", () => {
    const onRefresh = vi.fn();
    const intervalMs = 10_000;

    const { result } = renderHook(() =>
      useAutoRefresh({ intervalMs, enabled: true, onRefresh }),
    );

    // Advance 7 seconds into the cycle.
    act(() => { vi.advanceTimersByTime(7_000); });
    expect(onRefresh).not.toHaveBeenCalled();

    // refreshNow fires immediately.
    act(() => { result.current.refreshNow(); });
    expect(onRefresh).toHaveBeenCalledTimes(1);

    // The timer was reset, so after another 7s it should NOT fire yet
    // (it needs the full intervalMs from the reset point).
    act(() => { vi.advanceTimersByTime(7_000); });
    expect(onRefresh).toHaveBeenCalledTimes(1);

    // Complete the full interval from reset -> fires again.
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(onRefresh).toHaveBeenCalledTimes(2);
  });

  it("pauses when document becomes hidden and resumes on visible", () => {
    const onRefresh = vi.fn();
    const intervalMs = 5_000;

    renderHook(() =>
      useAutoRefresh({ intervalMs, enabled: true, onRefresh }),
    );

    // Hide the document halfway through the first interval.
    act(() => { vi.advanceTimersByTime(2_500); });
    act(() => { setDocumentHidden(true); });

    // Advance well past the interval -- should NOT fire while hidden.
    act(() => { vi.advanceTimersByTime(intervalMs * 5); });
    expect(onRefresh).not.toHaveBeenCalled();

    // Make visible again -- timers restart.
    act(() => { setDocumentHidden(false); });

    // Now a full interval fires.
    act(() => { vi.advanceTimersByTime(intervalMs); });
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("cleans up intervals on unmount", () => {
    const onRefresh = vi.fn();
    const intervalMs = 5_000;

    const { unmount } = renderHook(() =>
      useAutoRefresh({ intervalMs, enabled: true, onRefresh }),
    );

    unmount();

    // Advance time -- nothing should fire after unmount.
    act(() => { vi.advanceTimersByTime(intervalMs * 10); });
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("tracks nextRefreshIn countdown", () => {
    const onRefresh = vi.fn();
    const intervalMs = 5_000;

    const { result } = renderHook(() =>
      useAutoRefresh({ intervalMs, enabled: true, onRefresh }),
    );

    // Initially should be the full interval.
    expect(result.current.nextRefreshIn).toBe(intervalMs);

    // After 2 seconds the countdown should have decreased.
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(result.current.nextRefreshIn).toBe(3_000);

    // After full interval, resets. Advance 3s + 1s extra to let the reset tick propagate.
    act(() => { vi.advanceTimersByTime(4_000); });
    // onRefresh fires and nextRefreshIn resets; timer ticks reduce it by the overshoot.
    expect(result.current.nextRefreshIn).toBeLessThanOrEqual(intervalMs);
    expect(result.current.nextRefreshIn).toBeGreaterThan(0);
  });

  it("starts disabled when enabled=false", () => {
    const onRefresh = vi.fn();

    const { result } = renderHook(() =>
      useAutoRefresh({ intervalMs: 5_000, enabled: false, onRefresh }),
    );

    expect(result.current.isEnabled).toBe(false);

    act(() => { vi.advanceTimersByTime(30_000); });
    expect(onRefresh).not.toHaveBeenCalled();
  });
});

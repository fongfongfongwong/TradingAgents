import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ReactNode } from "react";

// Mock localStorage for jsdom environments that don't support it
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
    get length() { return Object.keys(store).length; },
    key: (i: number) => Object.keys(store)[i] ?? null,
  };
})();
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, writable: true });

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Track the ticker value the provider exposes.
let mockTicker = "AAPL";

vi.mock("@/hooks/useTicker", () => ({
  useTicker: () => ({
    ticker: mockTicker,
    setTicker: vi.fn(),
    watchlist: [],
    addToWatchlist: vi.fn(),
    removeFromWatchlist: vi.fn(),
  }),
}));

const mockStartAnalysisV3 = vi.fn().mockResolvedValue({ analysis_id: "a1" });
const mockGetAnalysisV3 = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/lib/api");
  return {
    ...actual,
    startAnalysisV3: (...args: unknown[]) => mockStartAnalysisV3(...args),
    getAnalysisV3: (...args: unknown[]) => mockGetAnalysisV3(...args),
  };
});

const mockConnectV3 = vi.fn();
const mockDisconnect = vi.fn();

vi.mock("@/hooks/useSSE", () => ({
  useSSE: () => ({
    events: [],
    isConnected: false,
    error: null,
    connect: vi.fn(),
    connectV3: mockConnectV3,
    disconnect: mockDisconnect,
  }),
}));

// Zustand store mock — we control the items array.
let mockStoreItems: Array<{
  ticker: string;
  signal: string;
  conviction: number;
  tier: number;
  expected_value_pct: number | null;
  thesis_confidence: number | null;
  antithesis_confidence: number | null;
  disagreement_score: number | null;
  final_shares: number;
  pipeline_latency_ms: number;
  data_gaps: string[];
  cached: boolean;
}> = [];

vi.mock("@/stores/signalsStore", () => ({
  useSignalsStore: (selector: (s: { items: typeof mockStoreItems }) => unknown) =>
    selector({ items: mockStoreItems }),
}));

// Lazy import so mocks are in place.
let AnalysisTab: typeof import("../AnalysisTab").default;

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockTicker = "AAPL";
  mockStoreItems = [];
  mockStartAnalysisV3.mockClear();
  mockConnectV3.mockClear();
  mockDisconnect.mockClear();
  try { localStorage.clear(); } catch { /* jsdom may not support localStorage */ }

  // Re-import to pick up fresh module state.
  const mod = await import("../AnalysisTab");
  AnalysisTab = mod.default;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("AnalysisTab auto-run", () => {
  it("auto-triggers startAnalysisV3 when autoRun is ON and ticker changes", async () => {
    // autoRun defaults to true (nothing in localStorage).
    const { rerender } = render(<AnalysisTab />);

    // The initial render should NOT trigger (no ticker *change* — first mount).
    // We need a ticker change.  Simulate by changing mockTicker and re-rendering.
    mockTicker = "TSLA";
    rerender(<AnalysisTab />);

    // Advance past the 80ms debounce.
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(mockStartAnalysisV3).toHaveBeenCalledWith({ ticker: "TSLA" });
  });

  it("does NOT auto-trigger when autoRun is OFF", async () => {
    localStorage.setItem("analysis-auto-run", "false");

    // Re-import to pick up localStorage.
    const mod = await import("../AnalysisTab");
    const Tab = mod.default;

    const { rerender } = render(<Tab />);

    mockTicker = "TSLA";
    rerender(<Tab />);

    await act(async () => {
      vi.advanceTimersByTime(200);
    });

    expect(mockStartAnalysisV3).not.toHaveBeenCalled();
  });

  it("renders InspectorCard from cached BatchSignalItem before pipeline completes", async () => {
    mockStoreItems = [
      {
        ticker: "AAPL",
        signal: "BUY",
        conviction: 82,
        tier: 1,
        expected_value_pct: 5.3,
        thesis_confidence: 75,
        antithesis_confidence: 40,
        disagreement_score: 0.35,
        final_shares: 100,
        pipeline_latency_ms: 14000,
        data_gaps: [],
        cached: true,
      },
    ];

    // autoRun OFF so the pipeline doesn't start and we can inspect the cached card.
    localStorage.setItem("analysis-auto-run", "false");
    const mod = await import("../AnalysisTab");
    const Tab = mod.default;

    render(<Tab />);

    // With cached data and idle state, InspectorCard renders directly (no Run button needed).
    // The cached InspectorCard should show the signal "BUY" immediately.
    const buyBadges = screen.getAllByText("BUY");
    expect(buyBadges.length).toBeGreaterThan(0);
  });
});

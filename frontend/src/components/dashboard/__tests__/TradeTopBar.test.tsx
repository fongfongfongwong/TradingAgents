import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock("@/lib/api", () => ({
  getCostsToday: vi.fn().mockResolvedValue({
    date: "2026-04-06",
    total_usd: 12.34,
    budget_daily_usd: 300,
    budget_per_ticker_usd: 10,
    pct_of_daily_budget: 4.11,
    by_agent: {},
    by_ticker: {},
    by_model: {},
    call_count: 42,
    budget_breached: false,
  }),
}));

vi.mock("@/stores/signalsStore", () => {
  const fn = vi.fn();
  // Simple selector-based mock: call selector with a fake state and return result.
  const fakeState = {
    items: [],
    prevItems: [],
    batchId: null,
    batchProgress: { total: 40, completed: 12, failed: 0, running: 2 },
    lastRefreshedAt: null,
  };
  fn.mockImplementation((selector: (s: typeof fakeState) => unknown) =>
    selector(fakeState),
  );
  return { useSignalsStore: fn };
});

/* ------------------------------------------------------------------ */
/*  Import component AFTER mocks are wired                             */
/* ------------------------------------------------------------------ */

import TradeTopBar from "../TradeTopBar";

/* ------------------------------------------------------------------ */
/*  Setup / teardown                                                   */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("TradeTopBar", () => {
  it("renders LIVE pill", () => {
    render(<TradeTopBar />);
    expect(screen.getByTestId("live-pill")).toHaveTextContent("LIVE");
  });

  it("renders market clock", () => {
    render(<TradeTopBar />);
    const clock = screen.getByTestId("market-clock");
    expect(clock).toBeInTheDocument();
    // Should show one of the market phases
    expect(clock.textContent).toMatch(/RTH|PRE|POST|CLOSED/);
    // Should show ET label
    expect(clock.textContent).toMatch(/ET/);
  });

  it("renders 3 countdown sections", () => {
    render(<TradeTopBar />);
    expect(screen.getByTestId("countdown-universe")).toBeInTheDocument();
    expect(screen.getByTestId("countdown-agent")).toBeInTheDocument();
    expect(screen.getByTestId("countdown-trade")).toBeInTheDocument();
  });

  it("renders 9 source chips", () => {
    render(<TradeTopBar />);
    const strip = screen.getByTestId("source-strip");
    expect(strip).toBeInTheDocument();

    const sourceNames = [
      "polygon",
      "yfin",
      "finnhub",
      "quiver",
      "cboe",
      "apewis",
      "fred",
      "f&g",
      "anthropic",
    ];

    for (const name of sourceNames) {
      expect(screen.getByTestId(`source-chip-${name}`)).toBeInTheDocument();
    }
  });

  it("renders budget meter", () => {
    render(<TradeTopBar />);
    const meter = screen.getByTestId("budget-meter");
    expect(meter).toBeInTheDocument();
    expect(meter.textContent).toMatch(/Budget/);
    expect(meter.textContent).toMatch(/\$.*\/.*\$300/);
  });
});

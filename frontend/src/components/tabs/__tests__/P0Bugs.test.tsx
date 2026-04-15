import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock("@/hooks/useTicker", () => ({
  useTicker: () => ({
    ticker: "AAPL",
    setTicker: vi.fn(),
    watchlist: [],
    addToWatchlist: vi.fn(),
    removeFromWatchlist: vi.fn(),
  }),
}));

const mockRunBacktest = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/lib/api");
  return {
    ...actual,
    runBacktest: (...args: unknown[]) => mockRunBacktest(...args),
  };
});

/* ------------------------------------------------------------------ */
/*  P0-5: BacktestTab error handling                                   */
/* ------------------------------------------------------------------ */

import BacktestTab from "../BacktestTab";

describe("P0-5: BacktestTab error handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does NOT show sample metrics when backtest fails", async () => {
    mockRunBacktest.mockRejectedValueOnce(new Error("Network error"));

    render(<BacktestTab />);

    // Click "Run Backtest"
    const runBtn = screen.getByRole("button", { name: /run backtest/i });
    fireEvent.click(runBtn);

    // Wait for error message
    await waitFor(() => {
      expect(screen.getByText(/backtest failed/i)).toBeTruthy();
    });

    // Verify sample metrics are NOT displayed
    expect(screen.queryByText("Total Return")).toBeNull();
    expect(screen.queryByText("Sharpe Ratio")).toBeNull();
    expect(screen.queryByText("28.34%")).toBeNull();
    expect(screen.queryByText("1.42")).toBeNull();
  });

  it("shows sample data only when user clicks View Sample explicitly", async () => {
    render(<BacktestTab />);

    // "View Sample" button should be visible when no result
    const sampleBtn = screen.getByRole("button", { name: /view sample/i });
    fireEvent.click(sampleBtn);

    // Now sample metrics should be shown
    await waitFor(() => {
      expect(screen.getByText("Total Return")).toBeTruthy();
    });
    expect(screen.getByText("Showing sample backtest data.")).toBeTruthy();
  });

  it("shows real results on successful backtest", async () => {
    mockRunBacktest.mockResolvedValueOnce({
      ticker: "AAPL",
      metrics: {
        total_return: 0.15,
        sharpe_ratio: 1.1,
        max_drawdown: -0.05,
        win_rate: 0.6,
        total_trades: 5,
        winning_trades: 3,
        total_pnl: 5000,
        sortino_ratio: 1.5,
        annual_return: 0.18,
      },
      trades_count: 5,
    });

    render(<BacktestTab />);

    const runBtn = screen.getByRole("button", { name: /run backtest/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(screen.getByText("Total Return")).toBeTruthy();
    });

    // Should NOT show error
    expect(screen.queryByText(/backtest failed/i)).toBeNull();
    // Should NOT show sample banner
    expect(screen.queryByText("Showing sample backtest data.")).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/*  P0-1: Tab components exist and are importable                      */
/* ------------------------------------------------------------------ */

import ChartTab from "../ChartTab";
import OptionsTab from "../OptionsTab";
import HoldingsTab from "../HoldingsTab";
import SettingsTab from "../SettingsTab";

describe("P0-1: Tab components render without crashing", () => {
  it("ChartTab renders", () => {
    const { container } = render(<ChartTab />);
    expect(container.firstChild).toBeTruthy();
  });

  it("OptionsTab renders", () => {
    const { container } = render(<OptionsTab />);
    expect(container.firstChild).toBeTruthy();
  });

  it("HoldingsTab renders", () => {
    const { container } = render(<HoldingsTab />);
    expect(container.firstChild).toBeTruthy();
  });

  it("SettingsTab renders", () => {
    const { container } = render(<SettingsTab />);
    expect(container.firstChild).toBeTruthy();
  });

  it("BacktestTab renders", () => {
    const { container } = render(<BacktestTab />);
    expect(container.firstChild).toBeTruthy();
  });
});

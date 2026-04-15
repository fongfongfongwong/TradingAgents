import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import RunAllProgressModal from "../RunAllProgressModal";

/* ------------------------------------------------------------------ */
/*  Fake EventSource                                                   */
/* ------------------------------------------------------------------ */

type Listener = (evt: MessageEvent) => void;

class FakeEventSource {
  public static instances: FakeEventSource[] = [];
  public url: string;
  public closed = false;
  public onerror: ((e: Event) => void) | null = null;
  private listeners: Record<string, Listener[]> = {};

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener): void {
    this.listeners[type] = this.listeners[type] ?? [];
    this.listeners[type].push(listener as unknown as Listener);
  }

  removeEventListener(type: string, listener: EventListener): void {
    const arr = this.listeners[type];
    if (!arr) return;
    this.listeners[type] = arr.filter(
      (l) => l !== (listener as unknown as Listener),
    );
  }

  close(): void {
    this.closed = true;
  }

  /** Test helper: fire a named event with the given JSON payload. */
  emit(type: string, payload: unknown): void {
    const listeners = this.listeners[type] ?? [];
    const evt = new MessageEvent(type, { data: JSON.stringify(payload) });
    for (const l of listeners) l(evt);
  }
}

/* ------------------------------------------------------------------ */
/*  Mock the api module                                                */
/* ------------------------------------------------------------------ */

vi.mock("@/lib/api", () => ({
  batchStreamUrl: (batchId: string) => `http://test/stream/${batchId}`,
  getBatchStatus: vi.fn(async (_batchId: string) => ({
    batch_id: _batchId,
    total: 3,
    completed: 2,
    failed: 0,
    running: 0,
    status: "complete" as const,
    last_ticker: "MSFT",
    last_signal: "BUY",
    total_cost_usd: 0.12,
    results: [
      {
        ticker: "AAPL",
        signal: "BUY" as const,
        conviction: 75,
        tier: 1,
        expected_value_pct: 3.2,
        thesis_confidence: 70,
        antithesis_confidence: 40,
        disagreement_score: 0.5,
        final_shares: 4,
        pipeline_latency_ms: 1200,
        data_gaps: [],
        cached: false,
        cost_usd: 0.05,
      },
      {
        ticker: "MSFT",
        signal: "BUY" as const,
        conviction: 60,
        tier: 2,
        expected_value_pct: 2.1,
        thesis_confidence: 62,
        antithesis_confidence: 50,
        disagreement_score: 0.4,
        final_shares: 3,
        pipeline_latency_ms: 1100,
        data_gaps: [],
        cached: false,
        cost_usd: 0.07,
      },
    ],
  })),
}));

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  FakeEventSource.instances = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).EventSource = FakeEventSource;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).EventSource = FakeEventSource;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function latestEs(): FakeEventSource {
  const es = FakeEventSource.instances.at(-1);
  if (!es) throw new Error("no EventSource instance created");
  return es;
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("RunAllProgressModal", () => {
  it("renders initial tickers in pending state", () => {
    render(
      <RunAllProgressModal
        batchId="abc123"
        initialTickers={["AAPL", "MSFT", "NVDA"]}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    );

    expect(screen.getByText("Run All — Fresh Pipeline")).toBeInTheDocument();

    for (const t of ["AAPL", "MSFT", "NVDA"]) {
      const row = screen.getByTestId(`ticker-row-${t}`);
      expect(row).toBeInTheDocument();
      expect(row.getAttribute("data-status")).toBe("pending");
    }
  });

  it("updates per-ticker state from SSE events", async () => {
    render(
      <RunAllProgressModal
        batchId="abc123"
        initialTickers={["AAPL", "MSFT"]}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    );

    const es = latestEs();

    await act(async () => {
      es.emit("ticker_start", { ticker: "AAPL" });
    });
    expect(
      screen.getByTestId("ticker-row-AAPL").getAttribute("data-status"),
    ).toBe("running");

    await act(async () => {
      es.emit("ticker_done", {
        ticker: "AAPL",
        signal: "BUY",
        conviction: 75,
        cost_usd: 0.05,
      });
    });
    expect(
      screen.getByTestId("ticker-row-AAPL").getAttribute("data-status"),
    ).toBe("complete");

    await act(async () => {
      es.emit("progress", {
        total: 2,
        completed: 1,
        failed: 0,
        running: 1,
        last_ticker: "AAPL",
        last_signal: "BUY",
      });
    });

    // Header "Completed" chip reflects the progress event.
    const completedChip = screen.getByText("Completed").nextSibling;
    expect(completedChip?.textContent).toBe("1");
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <RunAllProgressModal
        batchId="abc123"
        initialTickers={["AAPL"]}
        onClose={onClose}
        onComplete={() => {}}
      />,
    );

    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when Escape key is pressed", () => {
    const onClose = vi.fn();
    render(
      <RunAllProgressModal
        batchId="abc123"
        initialTickers={["AAPL"]}
        onClose={onClose}
        onComplete={() => {}}
      />,
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes EventSource on unmount", () => {
    const { unmount } = render(
      <RunAllProgressModal
        batchId="abc123"
        initialTickers={["AAPL"]}
        onClose={() => {}}
        onComplete={() => {}}
      />,
    );

    const es = latestEs();
    expect(es.closed).toBe(false);
    unmount();
    expect(es.closed).toBe(true);
  });
});

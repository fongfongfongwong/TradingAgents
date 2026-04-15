"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTicker } from "@/hooks/useTicker";
import {
  getPriceData,
  getRVForecast,
  type PriceBar,
  type RVForecastResponse,
} from "@/lib/api";
import {
  computeATR,
  computeBollinger,
  computeKeltner,
  computeMACD,
  computeRSI,
  computeSqueeze,
  computeTpSl,
  type MacdPoint,
  type RsiPoint,
  type TpSlResult,
} from "@/lib/indicators";

const RANGES = ["1mo", "3mo", "6mo", "1y", "2y", "5y"] as const;

// Pane layout - four price scales share the same chart. Margins below
// are fractional heights; values must not overlap. Layout:
//   candles : top    0.05 -> bottom 0.40  (main pane, ~55%)
//   volume  : top    0.53 -> bottom 0.40  (overlay inside candle pane footer)
//   rsi     : top    0.62 -> bottom 0.22  (~16%)
//   macd    : top    0.82 -> bottom 0     (~18%)
const CANDLE_MARGINS = { top: 0.05, bottom: 0.4 } as const;
const VOLUME_MARGINS = { top: 0.53, bottom: 0.4 } as const;
const RSI_MARGINS = { top: 0.62, bottom: 0.22 } as const;
const MACD_MARGINS = { top: 0.82, bottom: 0 } as const;

interface SignalMarker {
  time: string;
  position: "belowBar" | "aboveBar";
  color: string;
  shape: "arrowUp" | "arrowDown";
  text: string;
}

interface LegendValues {
  rsi: number | null;
  macd: number | null;
  signal: number | null;
  histogram: number | null;
}

/**
 * Derive long/short signal markers from aligned RSI + MACD outputs.
 * Rules are documented in the spec; this is a pure function over pre-computed
 * indicator arrays.
 */
function deriveSignals(
  bars: readonly PriceBar[],
  rsi: readonly RsiPoint[],
  macd: readonly MacdPoint[],
): SignalMarker[] {
  if (rsi.length === 0 || macd.length === 0) return [];

  // Index by bar time for O(1) alignment. A Map preserves clarity over
  // parallel index math because the two series have different warmups.
  const rsiByTime = new Map<string, number>();
  for (const p of rsi) rsiByTime.set(p.time, p.value);

  const macdByTime = new Map<string, MacdPoint>();
  for (const p of macd) macdByTime.set(p.time, p);

  const markers: SignalMarker[] = [];
  const seenTimes = new Set<string>();

  const pushMarker = (m: SignalMarker, priority: boolean): void => {
    if (seenTimes.has(m.time)) {
      if (priority) {
        // Replace lower-priority marker with the golden/death cross one.
        const idx = markers.findIndex((x) => x.time === m.time);
        if (idx >= 0) markers[idx] = m;
      }
      return;
    }
    seenTimes.add(m.time);
    markers.push(m);
  };

  // First pass: golden/death cross (higher priority).
  for (let i = 1; i < bars.length; i += 1) {
    const tCurr = bars[i].time;
    const tPrev = bars[i - 1].time;
    const mCurr = macdByTime.get(tCurr);
    const mPrev = macdByTime.get(tPrev);
    const rCurr = rsiByTime.get(tCurr);
    if (!mCurr || !mPrev || rCurr === undefined) continue;

    const crossedAbove =
      mPrev.macd <= mPrev.signal && mCurr.macd > mCurr.signal;
    const crossedBelow =
      mPrev.macd >= mPrev.signal && mCurr.macd < mCurr.signal;

    if (crossedAbove && rCurr > 50) {
      pushMarker(
        {
          time: tCurr,
          position: "belowBar",
          color: "#22ff88",
          shape: "arrowUp",
          text: "GC",
        },
        true,
      );
    } else if (crossedBelow && rCurr < 50) {
      pushMarker(
        {
          time: tCurr,
          position: "aboveBar",
          color: "#ff3355",
          shape: "arrowDown",
          text: "DC",
        },
        true,
      );
    }
  }

  // Second pass: RSI threshold crossings confirmed by histogram flip.
  for (let i = 1; i < bars.length; i += 1) {
    const tCurr = bars[i].time;
    const tPrev = bars[i - 1].time;
    const rCurr = rsiByTime.get(tCurr);
    const rPrev = rsiByTime.get(tPrev);
    const mCurr = macdByTime.get(tCurr);
    const mPrev = macdByTime.get(tPrev);
    if (
      rCurr === undefined ||
      rPrev === undefined ||
      mCurr === undefined ||
      mPrev === undefined
    ) {
      continue;
    }

    const rsiCrossedUp30 = rPrev <= 30 && rCurr > 30;
    const rsiCrossedDown70 = rPrev >= 70 && rCurr < 70;
    const histPositiveNow = mCurr.histogram > 0 && mPrev.histogram <= 0;
    const histNegativeNow = mCurr.histogram < 0 && mPrev.histogram >= 0;
    const histPositiveRecent = mCurr.histogram > 0 || histPositiveNow;
    const histNegativeRecent = mCurr.histogram < 0 || histNegativeNow;

    if (rsiCrossedUp30 && histPositiveRecent) {
      pushMarker(
        {
          time: tCurr,
          position: "belowBar",
          color: "#10b981",
          shape: "arrowUp",
          text: "L",
        },
        false,
      );
    } else if (rsiCrossedDown70 && histNegativeRecent) {
      pushMarker(
        {
          time: tCurr,
          position: "aboveBar",
          color: "#e23b4a",
          shape: "arrowDown",
          text: "S",
        },
        false,
      );
    }
  }

  markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  return markers;
}

export default function ChartTab() {
  const { ticker } = useTicker();
  const [range, setRange] = useState<string>("6mo");
  const [bars, setBars] = useState<PriceBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRsi, setShowRsi] = useState<boolean>(true);
  const [showMacd, setShowMacd] = useState<boolean>(true);
  const [showSignals, setShowSignals] = useState<boolean>(true);
  const [rvForecast1d, setRvForecast1d] = useState<RVForecastResponse | null>(null);
  const [rvForecast5d, setRvForecast5d] = useState<RVForecastResponse | null>(null);

  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setRvForecast1d(null);
    setRvForecast5d(null);
    Promise.all([
      getRVForecast(ticker, 1).catch(() => null),
      getRVForecast(ticker, 5).catch(() => null),
    ]).then(([f1, f5]) => {
      if (cancelled) return;
      setRvForecast1d(f1);
      setRvForecast5d(f5);
    });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getPriceData(ticker, range)
      .then((data) => {
        setBars(data);
      })
      .catch(() => {
        setError("Failed to load price data. Backend may need /api/price endpoint.");
        setBars([]);
      })
      .finally(() => setLoading(false));
  }, [ticker, range]);

  const rsiPoints = useMemo<RsiPoint[]>(() => computeRSI(bars, 14), [bars]);
  const macdPoints = useMemo<MacdPoint[]>(
    () => computeMACD(bars, 12, 26, 9),
    [bars],
  );
  const signalMarkers = useMemo<SignalMarker[]>(
    () => deriveSignals(bars, rsiPoints, macdPoints),
    [bars, rsiPoints, macdPoints],
  );

  const legend = useMemo<LegendValues>(() => {
    const lastRsi = rsiPoints.length > 0 ? rsiPoints[rsiPoints.length - 1] : null;
    const lastMacd =
      macdPoints.length > 0 ? macdPoints[macdPoints.length - 1] : null;
    return {
      rsi: lastRsi ? lastRsi.value : null,
      macd: lastMacd ? lastMacd.macd : null,
      signal: lastMacd ? lastMacd.signal : null,
      histogram: lastMacd ? lastMacd.histogram : null,
    };
  }, [rsiPoints, macdPoints]);

  // Volatility trading indicators
  const tpSl = useMemo<TpSlResult | null>(() => computeTpSl(bars), [bars]);
  const latestAtr = useMemo(() => {
    const arr = computeATR(bars);
    return arr.length > 0 ? arr[arr.length - 1] : null;
  }, [bars]);
  const latestBB = useMemo(() => {
    const arr = computeBollinger(bars);
    return arr.length > 0 ? arr[arr.length - 1] : null;
  }, [bars]);
  const latestSqueeze = useMemo(() => {
    const arr = computeSqueeze(bars);
    return arr.length > 0 ? arr[arr.length - 1] : null;
  }, [bars]);

  useEffect(() => {
    if (!chartRef.current || bars.length === 0) return;

    let cancelled = false;
    let cleanup: (() => void) | null = null;

    import("lightweight-charts").then(
      ({ createChart, ColorType, LineStyle }) => {
        if (cancelled || !chartRef.current) return;

        chartRef.current.innerHTML = "";

        const chart = createChart(chartRef.current, {
          width: chartRef.current.clientWidth,
          height: chartRef.current.clientHeight,
          layout: {
            background: { type: ColorType.Solid, color: "#08090a" },
            textColor: "#8a8f98",
            fontSize: 11,
          },
          grid: {
            vertLines: { color: "rgba(255,255,255,0.02)" },
            horzLines: { color: "rgba(255,255,255,0.02)" },
          },
          crosshair: {
            vertLine: { color: "rgba(94,106,210,0.3)" },
            horzLine: { color: "rgba(94,106,210,0.3)" },
          },
          rightPriceScale: {
            borderColor: "rgba(255,255,255,0.08)",
          },
          timeScale: {
            borderColor: "rgba(255,255,255,0.08)",
            timeVisible: true,
          },
        });

        // --- Pane 1: Candlesticks ---------------------------------------
        const candlestickSeries = chart.addCandlestickSeries({
          upColor: "#10b981",
          downColor: "#e23b4a",
          borderDownColor: "#e23b4a",
          borderUpColor: "#10b981",
          wickDownColor: "#e23b4a",
          wickUpColor: "#10b981",
          priceScaleId: "right",
        });
        chart.priceScale("right").applyOptions({ scaleMargins: CANDLE_MARGINS });

        candlestickSeries.setData(
          bars.map((b) => ({
            time: b.time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          })) as never,
        );

        // --- Volume overlay ---------------------------------------------
        const volumeSeries = chart.addHistogramSeries({
          color: "rgba(94,106,210,0.3)",
          priceFormat: { type: "volume" as const },
          priceScaleId: "volume",
        });
        chart.priceScale("volume").applyOptions({ scaleMargins: VOLUME_MARGINS });
        volumeSeries.setData(
          bars.map((b) => ({
            time: b.time,
            value: b.volume,
            color:
              b.close >= b.open
                ? "rgba(16,185,129,0.3)"
                : "rgba(226,59,74,0.3)",
          })) as never,
        );

        // --- Pane 2: RSI -------------------------------------------------
        const rsiSeries = chart.addLineSeries({
          color: "#828fff",
          lineWidth: 2,
          priceScaleId: "rsi",
          lastValueVisible: false,
          priceLineVisible: false,
          visible: showRsi,
        });
        chart.priceScale("rsi").applyOptions({ scaleMargins: RSI_MARGINS });
        rsiSeries.setData(
          rsiPoints.map((p) => ({ time: p.time, value: p.value })) as never,
        );

        // Horizontal reference lines at 30 / 70 on the RSI pane.
        rsiSeries.createPriceLine({
          price: 70,
          color: "rgba(226,59,74,0.4)",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "70",
        });
        rsiSeries.createPriceLine({
          price: 30,
          color: "rgba(16,185,129,0.4)",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: "30",
        });

        // --- Pane 3: MACD ------------------------------------------------
        const macdHistSeries = chart.addHistogramSeries({
          priceScaleId: "macd",
          priceFormat: { type: "price", precision: 3, minMove: 0.001 },
          priceLineVisible: false,
          lastValueVisible: false,
          visible: showMacd,
        });
        chart.priceScale("macd").applyOptions({ scaleMargins: MACD_MARGINS });
        macdHistSeries.setData(
          macdPoints.map((p) => ({
            time: p.time,
            value: p.histogram,
            color:
              p.histogram >= 0
                ? "rgba(16,185,129,0.55)"
                : "rgba(226,59,74,0.55)",
          })) as never,
        );

        const macdLineSeries = chart.addLineSeries({
          color: "#5e6ad2",
          lineWidth: 2,
          priceScaleId: "macd",
          priceFormat: { type: "price", precision: 3, minMove: 0.001 },
          lastValueVisible: false,
          priceLineVisible: false,
          visible: showMacd,
        });
        macdLineSeries.setData(
          macdPoints.map((p) => ({ time: p.time, value: p.macd })) as never,
        );

        const macdSignalSeries = chart.addLineSeries({
          color: "#f59e0b",
          lineWidth: 2,
          priceScaleId: "macd",
          priceFormat: { type: "price", precision: 3, minMove: 0.001 },
          lastValueVisible: false,
          priceLineVisible: false,
          visible: showMacd,
        });
        macdSignalSeries.setData(
          macdPoints.map((p) => ({ time: p.time, value: p.signal })) as never,
        );

        // --- Signal markers ---------------------------------------------
        if (showSignals) {
          candlestickSeries.setMarkers(
            signalMarkers.map((m) => ({
              time: m.time,
              position: m.position,
              color: m.color,
              shape: m.shape,
              text: m.text,
            })) as never,
          );
        }

        chart.timeScale().fitContent();

        const observer = new ResizeObserver((entries) => {
          for (const entry of entries) {
            chart.applyOptions({
              width: entry.contentRect.width,
              height: entry.contentRect.height,
            });
          }
        });
        observer.observe(chartRef.current);

        cleanup = () => {
          observer.disconnect();
          chart.remove();
        };
      },
    );

    return () => {
      cancelled = true;
      if (cleanup) cleanup();
    };
  }, [bars, rsiPoints, macdPoints, signalMarkers, showRsi, showMacd, showSignals]);

  const fmt = (v: number | null, digits: number = 2): string =>
    v === null || !Number.isFinite(v) ? "—" : v.toFixed(digits);

  const histColor =
    legend.histogram === null
      ? "text-[#8a8f98]"
      : legend.histogram >= 0
        ? "text-[#10b981]"
        : "text-[#e23b4a]";

  const toggleClass = (active: boolean): string =>
    `rounded px-2 py-1 text-[10px] font-medium transition-colors ${
      active
        ? "bg-[#5e6ad2]/20 text-[#828fff]"
        : "text-[#8a8f98] hover:bg-white/[0.03] hover:text-[#d0d6e0]"
    }`;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between gap-4">
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-bold text-[#f7f8f8]">{ticker}</h2>
          {bars.length > 0 && (
            <span className="font-mono text-sm text-[#d0d6e0]">
              Last: ${bars[bars.length - 1].close.toFixed(2)}
            </span>
          )}
          {(rvForecast1d || rvForecast5d) && (
            <span className="hidden font-mono text-[11px] text-[#8a8f98] md:inline">
              <span>RV 20d: </span>
              <span className="text-[#d0d6e0]">
                {fmt(rvForecast1d?.current_realized_vol_20d_pct ?? null, 1)}%
              </span>
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span>Pred 1d: </span>
              <span className="text-[#d0d6e0]">
                {fmt(rvForecast1d?.predicted_rv_pct ?? null, 1)}%
              </span>
              {rvForecast1d?.delta_pct != null && (
                <span
                  className={
                    rvForecast1d.delta_pct > 0
                      ? "ml-1 text-[#e23b4a]"
                      : rvForecast1d.delta_pct < 0
                        ? "ml-1 text-[#10b981]"
                        : "ml-1 text-[#8a8f98]"
                  }
                >
                  ({rvForecast1d.delta_pct > 0 ? "+" : ""}
                  {rvForecast1d.delta_pct.toFixed(1)})
                </span>
              )}
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span>Pred 5d: </span>
              <span className="text-[#d0d6e0]">
                {fmt(rvForecast5d?.predicted_rv_pct ?? null, 1)}%
              </span>
            </span>
          )}
          {bars.length > 0 && (
            <span className="hidden font-mono text-[11px] text-[#8a8f98] md:inline">
              <span>RSI(14): </span>
              <span className="text-[#d0d6e0]">{fmt(legend.rsi, 1)}</span>
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span>MACD: </span>
              <span className="text-[#d0d6e0]">{fmt(legend.macd, 2)}</span>
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span>Signal: </span>
              <span className="text-[#d0d6e0]">{fmt(legend.signal, 2)}</span>
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span>Hist: </span>
              <span className={`${histColor}`}>
                {legend.histogram === null
                  ? "—"
                  : `${legend.histogram >= 0 ? "+" : ""}${legend.histogram.toFixed(2)}`}
              </span>
            </span>
          )}
          {/* TP/SL & Vol indicators row */}
          {tpSl && (
            <span className="hidden font-mono text-[11px] text-[#8a8f98] lg:inline">
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span>ATR: </span>
              <span className="text-[#d0d6e0]">{tpSl.atr.toFixed(2)}</span>
              <span className="text-[#6e7681]"> ({tpSl.atrPct.toFixed(1)}%)</span>
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span
                className={`font-bold ${
                  tpSl.signal === "LONG"
                    ? "text-[#10b981]"
                    : tpSl.signal === "SHORT"
                      ? "text-[#e23b4a]"
                      : "text-[#8a8f98]"
                }`}
              >
                {tpSl.signal}
              </span>
              <span className="mx-2 text-[#3a3f4a]">|</span>
              <span>TP: </span>
              <span className="text-[#10b981]">
                ${tpSl.takeProfit.toFixed(2)}
                <span className="text-[#6e7681]"> ({tpSl.takeProfitPct > 0 ? "+" : ""}{tpSl.takeProfitPct}%)</span>
              </span>
              <span className="mx-1 text-[#3a3f4a]">|</span>
              <span>SL: </span>
              <span className="text-[#e23b4a]">
                ${tpSl.stopLoss.toFixed(2)}
                <span className="text-[#6e7681]"> ({tpSl.stopLossPct}%)</span>
              </span>
              <span className="mx-1 text-[#3a3f4a]">|</span>
              <span>R:R </span>
              <span className="text-[#d0d6e0]">{tpSl.riskReward}</span>
              {latestSqueeze && (
                <>
                  <span className="mx-2 text-[#3a3f4a]">|</span>
                  <span
                    className={
                      latestSqueeze.squeeze
                        ? "text-[#f0883e] font-bold"
                        : "text-[#6e7681]"
                    }
                  >
                    {latestSqueeze.squeeze ? "SQUEEZE" : "no squeeze"}
                  </span>
                </>
              )}
              {latestBB && (
                <>
                  <span className="mx-2 text-[#3a3f4a]">|</span>
                  <span>BB%B: </span>
                  <span
                    className={
                      latestBB.pctB < 0.2
                        ? "text-[#10b981]"
                        : latestBB.pctB > 0.8
                          ? "text-[#e23b4a]"
                          : "text-[#d0d6e0]"
                    }
                  >
                    {(latestBB.pctB * 100).toFixed(0)}%
                  </span>
                  <span className="mx-1 text-[#3a3f4a]">|</span>
                  <span>BW: </span>
                  <span className="text-[#d0d6e0]">{latestBB.bandwidth.toFixed(1)}%</span>
                </>
              )}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Indicator toggles */}
          <div className="flex gap-1">
            <button
              onClick={() => setShowRsi((v) => !v)}
              className={toggleClass(showRsi)}
              aria-pressed={showRsi}
            >
              RSI
            </button>
            <button
              onClick={() => setShowMacd((v) => !v)}
              className={toggleClass(showMacd)}
              aria-pressed={showMacd}
            >
              MACD
            </button>
            <button
              onClick={() => setShowSignals((v) => !v)}
              className={toggleClass(showSignals)}
              aria-pressed={showSignals}
            >
              SIGNALS
            </button>
          </div>

          {/* Range selector */}
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={toggleClass(range === r)}
              >
                {r.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart area */}
      <div className="relative flex-1 overflow-hidden rounded border border-white/[0.08]">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#08090a]/80">
            <span className="text-xs text-[#8a8f98]">Loading chart...</span>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#08090a]/80">
            <span className="text-xs text-[#e23b4a]">{error}</span>
          </div>
        )}
        <div ref={chartRef} className="h-full w-full" />
      </div>
    </div>
  );
}

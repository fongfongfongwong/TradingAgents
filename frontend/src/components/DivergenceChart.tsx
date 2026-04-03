"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { DivergenceDimension } from "@/lib/api";

interface DivergenceChartProps {
  dimensions: DivergenceDimension[];
}

export default function DivergenceChart({ dimensions }: DivergenceChartProps) {
  const chartData = dimensions.map((d) => ({
    name: d.name,
    bull: d.bull_score,
    bear: -d.bear_score, // negative so bars go in opposite direction
    divergence: d.divergence,
  }));

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-800/20 p-4">
      <h3 className="mb-4 text-sm font-semibold text-gray-300">
        Bull vs Bear Scores by Dimension
      </h3>

      <ResponsiveContainer width="100%" height={320}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 5, right: 30, left: 80, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis
            type="number"
            domain={[-1, 1]}
            tick={{ fill: "#9ca3af", fontSize: 12 }}
            axisLine={{ stroke: "#4b5563" }}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fill: "#d1d5db", fontSize: 12 }}
            axisLine={{ stroke: "#4b5563" }}
            width={70}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #374151",
              borderRadius: "8px",
              color: "#f3f4f6",
              fontSize: 12,
            }}
            formatter={(value: number, name: string) => {
              const abs = Math.abs(value).toFixed(2);
              const label = name === "bear" ? "Bear" : "Bull";
              return [abs, label];
            }}
          />
          <Legend
            formatter={(value: string) =>
              value === "bull" ? "Bull" : "Bear"
            }
            wrapperStyle={{ fontSize: 12, color: "#9ca3af" }}
          />
          <Bar dataKey="bull" name="bull" radius={[0, 4, 4, 0]}>
            {chartData.map((_, idx) => (
              <Cell key={idx} fill="#22c55e" />
            ))}
          </Bar>
          <Bar dataKey="bear" name="bear" radius={[4, 0, 0, 4]}>
            {chartData.map((_, idx) => (
              <Cell key={idx} fill="#ef4444" />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

"use client";

import React, { useMemo, useState } from "react";
import { TrendingUp } from "lucide-react";
import { formatCurrency } from "@/utils/format";

export interface ProgressionWindowData {
  label: string;
  value: number | null;
}

interface HistoricalProgressionChartProps {
  windows: ProgressionWindowData[];
  overallPnl?: number | null;
}

function formatCompactWindowPnl(val: number): string {
  const abs = Math.abs(val);
  const sign = val > 0 ? "+" : val < 0 ? "-" : "";
  if (abs >= 1_000_000) {
    const m = abs / 1_000_000;
    return `${sign}$${m.toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (abs >= 1_000) {
    return `${sign}$${(abs / 1_000).toFixed(0)}k`;
  }
  return `${sign}$${abs.toFixed(0)}`;
}

function formatWindowLabel(label: string): string {
  const cleaned = label.replace(/^Last\s+/i, "");
  if (cleaned === "1000") return "1k";
  if (cleaned === "1500") return "1.5k";
  if (cleaned === "2000") return "2k";
  if (cleaned === "3500") return "3.5k";
  if (cleaned === "5000" || cleaned === "5000+" || cleaned.toLowerCase() === "all") return "All";
  return cleaned;
}

export function HistoricalProgressionChart({
  windows,
}: HistoricalProgressionChartProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  // Only REAL window values are plotted. Null windows are gaps — we never
  // fabricate progression data.
  const chartData = useMemo(() => {
    const realWindows = windows.filter(
      (w): w is ProgressionWindowData & { value: number } =>
        w.value != null && !isNaN(Number(w.value))
    );
    const rawValues = realWindows.map((w) => Number(w.value));

    if (rawValues.length === 0) return null;

    const minVal = Math.min(...rawValues, 0);
    const maxVal = Math.max(...rawValues, 0);
    const range = maxVal - minVal || 1;

    const width = 600;
    const height = 130;
    const paddingLeft = 50;
    const paddingRight = 20;
    const paddingTop = 15;
    const paddingBottom = 20;

    const innerW = width - paddingLeft - paddingRight;
    const innerH = height - paddingTop - paddingBottom;

    const points =
      rawValues.length === 1
        ? [{ x: paddingLeft + innerW / 2, y: paddingTop + (1 - (rawValues[0] - minVal) / range) * innerH, val: rawValues[0] }]
        : rawValues.map((val, idx) => {
            const x = paddingLeft + (idx / (rawValues.length - 1)) * innerW;
            const normY = (val - minVal) / range;
            const y = paddingTop + (1 - normY) * innerH;
            return { x, y, val };
          });

    // Spline curve construction
    let splinePath = "";
    if (points.length > 0) {
      splinePath = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
      for (let i = 0; i < points.length - 1; i++) {
        const p0 = points[Math.max(0, i - 1)];
        const p1 = points[i];
        const p2 = points[i + 1];
        const p3 = points[Math.min(points.length - 1, i + 2)];

        const cp1x = p1.x + (p2.x - p0.x) / 6;
        const cp1y = p1.y + (p2.y - p0.y) / 6;
        const cp2x = p2.x - (p3.x - p1.x) / 6;
        const cp2y = p2.y - (p3.y - p1.y) / 6;

        splinePath += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
      }
    }

    const firstPt = points[0] || { x: paddingLeft, y: height - paddingBottom };
    const lastPt = points[points.length - 1] || { x: width - paddingRight, y: height - paddingBottom };
    const areaPath = `${splinePath} L ${lastPt.x.toFixed(1)} ${(height - paddingBottom).toFixed(1)} L ${firstPt.x.toFixed(1)} ${(height - paddingBottom).toFixed(1)} Z`;

    // 3 Y-Axis Ticks: max, mid, 0/min
    const yTicks = [
      { val: maxVal, y: paddingTop + 4 },
      { val: minVal + range * 0.5, y: paddingTop + innerH * 0.5 },
      { val: minVal, y: height - paddingBottom },
    ];

    return {
      width,
      height,
      points,
      splinePath,
      areaPath,
      yTicks,
      paddingLeft,
      paddingRight,
      innerW,
    };
  }, [windows]);

  // Map from window index -> plotted point index so hover syncs correctly
  const realIndexByWindow = useMemo(() => {
    const map: Record<number, number> = {};
    let realIdx = 0;
    windows.forEach((w, idx) => {
      if (w.value != null && !isNaN(Number(w.value))) {
        map[idx] = realIdx++;
      }
    });
    return map;
  }, [windows]);

  return (
    <div className="card p-5 rounded-2xl border border-border shadow-xs flex flex-col justify-between space-y-3 bg-surface h-full">
      {/* Card Header */}
      <div className="flex items-center gap-2">
        <TrendingUp size={14} className="text-purple-600" />
        <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
          Historical 10-Window Trade PnL Progression
        </h3>
      </div>

      {!chartData ? (
        <div className="flex items-center justify-center h-32 text-muted-fg text-xs">
          No resolved-position window data available for this wallet.
        </div>
      ) : (
        <>
          {/* SVG Progression Spline Chart with Purple Gradient & Y-Axis */}
          <div className="relative w-full h-32 select-none">
            <svg
              viewBox={`0 0 ${chartData.width} ${chartData.height}`}
              className="w-full h-full overflow-visible"
              preserveAspectRatio="none"
            >
              <defs>
                <linearGradient id="purple-progression-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8B5CF6" stopOpacity="0.25" />
                  <stop offset="60%" stopColor="#8B5CF6" stopOpacity="0.08" />
                  <stop offset="100%" stopColor="#8B5CF6" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Y Axis Grid lines & Ticks */}
              {chartData.yTicks.map((t, idx) => (
                <g key={idx}>
                  <text
                    x={chartData.paddingLeft - 8}
                    y={t.y + 3}
                    textAnchor="end"
                    className="text-[9px] font-mono fill-slate-400 font-medium"
                  >
                    {formatCurrency(t.val)}
                  </text>
                  <line
                    x1={chartData.paddingLeft}
                    y1={t.y}
                    x2={chartData.width - chartData.paddingRight}
                    y2={t.y}
                    stroke="#E2E8F0"
                    strokeDasharray="2 2"
                    strokeWidth="0.75"
                  />
                </g>
              ))}

              {/* Purple Area fill */}
              <path d={chartData.areaPath} fill="url(#purple-progression-grad)" />

              {/* Purple Spline line */}
              <path
                d={chartData.splinePath}
                fill="none"
                stroke="#7C3AED"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {/* Circular checkpoint dots */}
              {chartData.points.map((pt, idx) => {
                const isHovered = hoveredIdx !== null && realIndexByWindow[hoveredIdx] === idx;
                return (
                  <circle
                    key={idx}
                    cx={pt.x}
                    cy={pt.y}
                    r={isHovered ? 5.5 : 3.5}
                    fill="#7C3AED"
                    stroke="#FFFFFF"
                    strokeWidth="2"
                    className="transition-all cursor-pointer"
                  />
                );
              })}
            </svg>
          </div>

          {/* 10-Window Bottom Checkpoint Labels & Delta Values */}
          <div className="grid grid-cols-10 gap-0.5 pt-2 border-t border-border/50 text-center">
            {windows.map((w, idx) => {
              const hasValue = w.value != null && !isNaN(Number(w.value));
              const val = hasValue ? Number(w.value) : null;
              const isHovered = hoveredIdx === idx;
              const fullLabel = w.label || `Window ${idx + 1}`;
              const shortLabel = formatWindowLabel(fullLabel);
              const formattedVal = hasValue ? formatCompactWindowPnl(val!) : "—";
              const detailedVal = hasValue
                ? `${val! >= 0 ? "+" : ""}${val!.toLocaleString("en-US", { style: "currency", currency: "USD" })}`
                : "No data";

              return (
                <div
                  key={idx}
                  className={`flex flex-col items-center justify-center py-1 px-0.5 rounded transition-all cursor-default ${
                    isHovered ? "bg-surface-2 scale-105" : ""
                  }`}
                  title={`${fullLabel}: ${detailedVal}`}
                  onMouseEnter={() => setHoveredIdx(idx)}
                  onMouseLeave={() => setHoveredIdx(null)}
                >
                  <span className="text-[9px] font-medium text-muted-fg whitespace-nowrap block tracking-tight">
                    {shortLabel}
                  </span>
                  <span
                    className={`text-[9px] sm:text-[10px] font-bold font-mono mt-0.5 whitespace-nowrap block tracking-tighter ${
                      !hasValue
                        ? "text-muted-fg"
                        : val! >= 0
                          ? "text-green-600"
                          : "text-red-500"
                    }`}
                  >
                    {formattedVal}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

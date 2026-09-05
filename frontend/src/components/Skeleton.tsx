import React from "react";

export function SkeletonRow() {
  return (
    <div className="flex items-center justify-between p-4 border-b border-[#1a1a1a] w-full">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full skeleton" />
        <div className="space-y-2">
          <div className="w-32 h-3.5 rounded skeleton" />
          <div className="w-20 h-2.5 rounded skeleton" />
        </div>
      </div>
      <div className="space-y-2 flex flex-col items-end">
        <div className="w-16 h-3.5 rounded skeleton" />
        <div className="w-10 h-2.5 rounded skeleton" />
      </div>
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="card p-5 border-[#1a1a1a] bg-[#050505]">
      <div className="flex justify-between items-start mb-4">
        <div className="w-3/4 h-5 rounded skeleton" />
        <div className="w-12 h-6 rounded skeleton" />
      </div>
      <div className="w-1/2 h-3 rounded skeleton mb-6" />
      <div className="w-full h-1.5 rounded skeleton mb-4" />
      <div className="space-y-3 mt-4 pt-4 border-t border-[#1a1a1a]">
        <div className="flex justify-between">
          <div className="w-20 h-3 rounded skeleton" />
          <div className="w-16 h-3 rounded skeleton" />
        </div>
        <div className="flex justify-between">
          <div className="w-20 h-3 rounded skeleton" />
          <div className="w-16 h-3 rounded skeleton" />
        </div>
      </div>
    </div>
  );
}

export function SkeletonStatCard() {
  return (
    <div className="card p-5 border-[#1a1a1a] bg-[#050505]">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-4 h-4 rounded skeleton" />
        <div className="w-20 h-3 rounded skeleton" />
      </div>
      <div className="w-24 h-8 rounded skeleton" />
    </div>
  );
}

export function SkeletonKpiCards({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="p-3.5 rounded-xl bg-surface border border-border/90 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="w-16 h-2.5 rounded skeleton" />
            <div className="w-3.5 h-3.5 rounded skeleton" />
          </div>
          <div className="w-20 h-5 rounded skeleton" />
          <div className="w-24 h-2 rounded skeleton mt-2" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonTableRows({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <tbody className="divide-y divide-border/50">
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r}>
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c} className="py-2.5 px-3">
              <div
                className="h-3.5 rounded skeleton"
                style={{ width: `${c === 0 ? 70 : 45 + ((r + c) % 3) * 15}%` }}
              />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}

"use client";

import React from "react";

export function StatCard({
  label,
  icon,
  value,
  valueClassName = "text-foreground",
  subtitle,
}: {
  label: string;
  icon?: React.ReactNode;
  value: React.ReactNode;
  valueClassName?: string;
  subtitle?: React.ReactNode;
}) {
  return (
    <div className="card p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm text-muted-fg">{label}</span>
        {icon && (
          <span className="w-9 h-9 rounded-lg bg-surface-2 border border-border flex items-center justify-center text-subtle flex-shrink-0">
            {icon}
          </span>
        )}
      </div>
      <div className={`font-mono text-2xl font-bold leading-none ${valueClassName}`}>
        {value}
      </div>
      {subtitle && <div className="text-xs text-subtle">{subtitle}</div>}
    </div>
  );
}

export function StatCardRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
      {children}
    </div>
  );
}

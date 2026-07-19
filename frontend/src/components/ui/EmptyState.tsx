"use client";

import React from "react";

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      {icon && <div className="text-subtle mb-1">{icon}</div>}
      <div className="text-sm font-medium text-muted-fg">{title}</div>
      {hint && <div className="text-xs text-subtle max-w-sm">{hint}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

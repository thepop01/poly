"use client";

export interface PillTab {
  key: string;
  label: string;
  count?: number | null;
}

export function PillTabs({
  tabs,
  active,
  onChange,
  size = "md",
}: {
  tabs: readonly PillTab[];
  active: string;
  onChange: (key: string) => void;
  size?: "sm" | "md";
}) {
  const pad = size === "sm" ? "px-3 py-1 text-xs" : "px-4 py-1.5 text-sm";
  return (
    <div className="inline-flex items-center gap-1 p-1 rounded-lg bg-surface border border-border">
      {tabs.map((t) => {
        const isActive = t.key === active;
        return (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className={`${pad} rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer ${
              isActive
                ? "bg-surface-3 text-foreground"
                : "text-subtle hover:text-muted-fg"
            }`}
          >
            {t.label}
            {t.count !== undefined && t.count !== null && (
              <span className={`ml-1 ${isActive ? "text-muted-fg" : "text-subtle"}`}>
                ({t.count})
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

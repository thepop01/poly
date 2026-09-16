"use client";

import React, { useState, useRef, useEffect } from "react";
import { LayoutGrid, BarChart2, Zap, ArrowLeftRight, ChevronDown, Check } from "lucide-react";

export type WalletViewMode = "general" | "analytics" | "parlay" | "lineage";

interface ViewDropdownProps {
  value: WalletViewMode;
  onChange: (view: WalletViewMode) => void;
  disabled?: boolean;
}

interface ViewOption {
  key: WalletViewMode;
  label: string;
  badge: string;
  description: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  color: string;
  bgLight: string;
  borderColor: string;
}

const VIEW_OPTIONS: ViewOption[] = [
  {
    key: "general",
    label: "General",
    badge: "Core",
    description: "Standard performance, volume, PnL & win rate",
    icon: LayoutGrid,
    color: "text-foreground",
    bgLight: "bg-surface-2",
    borderColor: "border-border",
  },
  {
    key: "analytics",
    label: "Analytics",
    badge: "Brackets",
    description: "Price bucket hit-rates (<0.15 to >0.75)",
    icon: BarChart2,
    color: "text-foreground",
    bgLight: "bg-surface-2",
    borderColor: "border-border",
  },
  {
    key: "parlay",
    label: "Parlay",
    badge: "Multi-Leg",
    description: "Parlay win rate, bets, volume & open legs",
    icon: Zap,
    color: "text-foreground",
    bgLight: "bg-surface-2",
    borderColor: "border-border",
  },
  {
    key: "lineage",
    label: "Lineage",
    badge: "P2P",
    description: "Position transfers, transaction volume & funding",
    icon: ArrowLeftRight,
    color: "text-foreground",
    bgLight: "bg-surface-2",
    borderColor: "border-border",
  },
];

export function ViewDropdown({ value, onChange, disabled }: ViewDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const activeOption = VIEW_OPTIONS.find((opt) => opt.key === value) || VIEW_OPTIONS[0];
  const ActiveIcon = activeOption.icon;

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      {/* Dropdown Trigger Button */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen((prev) => !prev)}
        className={`flex items-center gap-2.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all duration-200 cursor-pointer select-none shadow-sm ${
          isOpen
            ? "bg-surface-2 border-primary/50 text-foreground ring-1 ring-primary/30"
            : "bg-surface border-border/80 text-foreground hover:bg-surface-2 hover:border-border"
        } ${disabled ? "opacity-40 pointer-events-none" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <div className={`p-1 rounded-lg ${activeOption.bgLight} ${activeOption.color}`}>
          <ActiveIcon size={14} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted-fg font-mono uppercase tracking-wider">View:</span>
          <span className="font-bold text-foreground">{activeOption.label}</span>
        </div>
        <ChevronDown
          size={14}
          className={`text-muted-fg transition-transform duration-200 ${isOpen ? "rotate-180 text-foreground" : ""}`}
        />
      </button>

      {/* Floating Menu Popover */}
      {isOpen && (
        <div
          role="listbox"
          className="absolute right-0 top-full mt-1.5 w-72 bg-surface/98 backdrop-blur-xl border border-border rounded-xl shadow-2xl z-50 p-1.5 flex flex-col gap-1 ring-1 ring-white/5 animate-in fade-in zoom-in-95 duration-150"
        >
          <div className="px-2.5 py-1 text-[10px] font-mono uppercase font-bold text-muted-fg border-b border-border/50 pb-1.5 mb-0.5">
            Select Table View Mode
          </div>

          {VIEW_OPTIONS.map((opt) => {
            const isSelected = opt.key === value;
            const Icon = opt.icon;
            return (
              <button
                key={opt.key}
                role="option"
                aria-selected={isSelected}
                onClick={() => {
                  onChange(opt.key);
                  setIsOpen(false);
                }}
                className={`flex items-center justify-between p-2 rounded-lg text-left transition-all duration-150 cursor-pointer ${
                  isSelected
                    ? "bg-surface-2 border border-border shadow-sm text-foreground"
                    : "hover:bg-surface-2/60 text-muted-fg hover:text-foreground border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className={`p-1.5 rounded-lg flex-shrink-0 ${opt.bgLight} ${opt.color}`}>
                    <Icon size={15} />
                  </div>
                  <div className="flex flex-col min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-xs font-bold ${isSelected ? "text-foreground" : "text-foreground/90"}`}>
                        {opt.label}
                      </span>
                      <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded-full border ${opt.bgLight} ${opt.color} ${opt.borderColor}`}>
                        {opt.badge}
                      </span>
                    </div>
                    <span className="text-[10px] text-muted-fg truncate max-w-[170px] leading-tight">
                      {opt.description}
                    </span>
                  </div>
                </div>

                {isSelected && (
                  <Check size={14} className="text-primary flex-shrink-0 ml-2" />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

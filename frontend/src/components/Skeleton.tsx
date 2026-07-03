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

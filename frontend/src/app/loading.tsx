import { SkeletonCard, SkeletonRow, SkeletonStatCard } from "@/components/Skeleton";

export default function Loading() {
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-center gap-4 bg-[#050505] p-4 rounded-xl border border-[#1a1a1a]">
        <div className="flex items-center gap-4 w-full md:w-auto">
          <div className="h-10 rounded-lg w-48 skeleton"></div>
          <div className="h-10 rounded-lg w-32 skeleton"></div>
        </div>
        <div className="ml-auto">
          <div className="h-8 rounded-lg w-24 skeleton"></div>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  );
}

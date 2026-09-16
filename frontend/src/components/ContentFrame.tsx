"use client";

import { usePathname } from "next/navigation";

export default function ContentFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const fullBleed = pathname.startsWith("/hub");
  return (
    <main
      className={`flex-1 min-h-0 bg-background ${
        fullBleed ? "overflow-hidden p-0" : "overflow-auto p-5"
      }`}
    >
      {children}
    </main>
  );
}

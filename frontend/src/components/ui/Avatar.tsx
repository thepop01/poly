"use client";

/** Deterministic colored-circle avatar with the first letter of the name/address. */
export function Avatar({
  name,
  address,
  size = 24,
}: {
  name?: string | null;
  address?: string | null;
  size?: number;
}) {
  const source = name?.trim() || address?.replace(/^0x/i, "") || "?";
  const letter = source.charAt(0).toUpperCase();

  const seed = address || name || "?";
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  const gradient = (hash % 5) + 1;

  return (
    <span
      className={`avatar-gradient-${gradient} inline-flex items-center justify-center rounded-full text-background font-bold flex-shrink-0 select-none`}
      style={{ width: size, height: size, fontSize: Math.max(10, size * 0.45) }}
    >
      {letter}
    </span>
  );
}

"use client";

import { useState } from "react";

export function useCopyAddress() {
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);

  const handleCopy = (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    navigator.clipboard.writeText(address);
    setCopiedAddress(address);
    setTimeout(() => setCopiedAddress(null), 2000);
  };

  return { copiedAddress, handleCopy };
}

"use client";

import React, { createContext, useContext, useEffect, useState } from "react";

interface ShellContextType {
  collapsed: boolean;
  toggleSidebar: () => void;
}

const ShellContext = createContext<ShellContextType>({
  collapsed: false,
  toggleSidebar: () => {},
});

const STORAGE_KEY = "pt-sidebar-collapsed";

export function ShellProvider({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      /* SSR / privacy mode */
    }
  }, []);

  const toggleSidebar = () => {
    setCollapsed((prev) => {
      try {
        localStorage.setItem(STORAGE_KEY, prev ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !prev;
    });
  };

  return (
    <ShellContext.Provider value={{ collapsed, toggleSidebar }}>
      {children}
    </ShellContext.Provider>
  );
}

export function useShell() {
  return useContext(ShellContext);
}

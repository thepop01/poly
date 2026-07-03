"use client";

import { useEffect, useState, createContext, useContext } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";

interface AuthContextType {
  token: string | null;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({ token: null, logout: () => {} });

export const useAuth = () => useContext(AuthContext);

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Try to get token from URL first
    const urlToken = searchParams.get("token");
    if (urlToken) {
      setToken(urlToken);
      localStorage.setItem("poly_auth_token", urlToken);
      
      // Clean up URL without triggering navigation
      const newUrl = window.location.pathname;
      window.history.replaceState({}, document.title, newUrl);
    } else {
      // Try to get from local storage
      const storedToken = localStorage.getItem("poly_auth_token");
      if (storedToken) {
        setToken(storedToken);
      }
    }
  }, [searchParams]);

  const logout = () => {
    setToken(null);
    localStorage.removeItem("poly_auth_token");
    router.refresh();
  };

  return (
    <AuthContext.Provider value={{ token, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

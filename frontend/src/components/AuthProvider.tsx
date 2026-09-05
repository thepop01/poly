"use client";

import { useEffect, useState, createContext, useContext } from "react";
import { useSearchParams, useRouter } from "next/navigation";

export interface AuthUser {
  id?: string;
  username?: string;
  email?: string;
  isGuest?: boolean;
}

interface AuthContextType {
  token: string | null;
  user: AuthUser | null;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({ token: null, user: null, logout: () => {} });

export const useAuth = () => useContext(AuthContext);

function decodeUser(token: string): AuthUser | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    const email = payload.email || "";
    const isGuest = typeof email === "string" && (email.startsWith("guest_") || email.endsWith("@polytracker.local"));
    return {
      id: payload.sub,
      username: payload.username || payload.name || payload.preferred_username || (isGuest ? "Guest" : email || "User"),
      email,
      isGuest,
    };
  } catch {
    return null;
  }
}

function saveToken(tok: string | null) {
  if (typeof window === "undefined") return;
  if (tok) {
    localStorage.setItem("poly_auth_token", tok);
    sessionStorage.setItem("poly_auth_token", tok);
  } else {
    localStorage.removeItem("poly_auth_token");
    sessionStorage.removeItem("poly_auth_token");
  }
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    // Try to get token from URL first
    const urlToken = searchParams.get("token");
    if (urlToken) {
      setToken(urlToken);
      saveToken(urlToken);

      // Clean up URL without triggering navigation
      const newUrl = window.location.pathname;
      window.history.replaceState({}, document.title, newUrl);
    } else {
      // Try to get from local or session storage
      const storedToken =
        localStorage.getItem("poly_auth_token") || sessionStorage.getItem("poly_auth_token");
      if (storedToken) {
        setToken(storedToken);
        saveToken(storedToken);
      } else {
        // Auto-provision a guest token so guest users can like/track seamlessly
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
        fetch(`${apiUrl}/api/auth/guest`, { method: "POST" })
          .then((r) => r.json())
          .then((data) => {
            if (data?.access_token) {
              setToken(data.access_token);
              saveToken(data.access_token);
            }
          })
          .catch(() => {});
      }
    }
  }, [searchParams]);

  const logout = () => {
    setToken(null);
    saveToken(null);
    router.refresh();
  };

  return (
    <AuthContext.Provider value={{ token, user: token ? decodeUser(token) : null, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

"use client";

import { useEffect, useState, createContext, useContext } from "react";
import { useSearchParams, useRouter } from "next/navigation";

export interface AuthUser {
  id?: string;
  username?: string;
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
    return {
      id: payload.sub,
      username: payload.username || payload.name || payload.preferred_username,
    };
  } catch {
    return null;
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
      sessionStorage.setItem("poly_auth_token", urlToken);

      // Clean up URL without triggering navigation
      const newUrl = window.location.pathname;
      window.history.replaceState({}, document.title, newUrl);
    } else {
      // Try to get from session storage
      const storedToken = sessionStorage.getItem("poly_auth_token");
      if (storedToken) {
        setToken(storedToken);
      } else {
        // Auto-provision a guest token so guest users can like/track seamlessly
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
        fetch(`${apiUrl}/api/auth/guest`, { method: "POST" })
          .then((r) => r.json())
          .then((data) => {
            if (data?.access_token) {
              setToken(data.access_token);
              sessionStorage.setItem("poly_auth_token", data.access_token);
            }
          })
          .catch(() => {});
      }
    }
  }, [searchParams]);

  const logout = () => {
    setToken(null);
    sessionStorage.removeItem("poly_auth_token");
    router.refresh();
  };

  return (
    <AuthContext.Provider value={{ token, user: token ? decodeUser(token) : null, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

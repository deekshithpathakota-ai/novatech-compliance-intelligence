import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, getToken, setToken, setUnauthorizedHandler } from "@/lib/api";
import type { User } from "@/types";

type Ctx = {
  user: User | null;
  ready: boolean;
  login: (body: { mode: "demo" | "sso" | "password"; role?: string; email?: string; password?: string }) => Promise<void>;
  logout: () => Promise<void>;
  can: (perm: string) => boolean;
};
const AuthCtx = React.createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [ready, setReady] = React.useState(false);
  const qc = useQueryClient();

  React.useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setUser(null);
    });
    if (!getToken()) {
      setReady(true);
      return;
    }
    api.get<User>("/api/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setReady(true));
  }, []);

  const login: Ctx["login"] = async (body) => {
    const r = await api.post<{ token: string; user: User }>("/api/auth/login", body);
    setToken(r.token);
    qc.clear();
    setUser(r.user);
  };
  const logout = async () => {
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* session may already be gone */
    }
    setToken(null);
    qc.clear();
    setUser(null);
  };
  const can = React.useCallback((perm: string) => !!user?.permissions.includes(perm), [user]);
  return <AuthCtx.Provider value={{ user, ready, login, logout, can }}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const c = React.useContext(AuthCtx);
  if (!c) throw new Error("useAuth outside provider");
  return c;
}

export function useTheme() {
  const [dark, setDark] = React.useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("nt-theme", next ? "dark" : "light");
    } catch {
      /* ignore */
    }
    setDark(next);
  };
  return { dark, toggle };
}

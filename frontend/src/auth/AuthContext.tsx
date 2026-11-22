import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, setCsrfToken, setUnauthorizedHandler } from "../api/client";
import type { User } from "../api/types";

type AuthState = {
  user: User | null;
  /** true, пока не известно, вошёл ли пользователь (первая проверка сессии). */
  loading: boolean;
  /** Ошибка первой проверки (например, нет сети) — отличается от «не вошёл». */
  bootError: string | null;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  retryBoot: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootAttempt, setBootAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setBootError(null);
    api<{ user: User }>("/auth/me", { silent401: true })
      .then((data) => !cancelled && setUser(data.user))
      .catch((error: ApiError) => {
        if (cancelled) return;
        setUser(null);
        if (error.status !== 401) setBootError(error.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [bootAttempt]);

  useEffect(() => {
    // Сессия истекла или отозвана: чистим личные данные из памяти и показываем вход.
    setUnauthorizedHandler(() => {
      setUser(null);
      queryClient.clear();
    });
    return () => setUnauthorizedHandler(null);
  }, [queryClient]);

  const login = useCallback(
    async (username: string, password: string) => {
      const data = await api<{ user: User; csrfToken: string }>("/auth/login", {
        method: "POST",
        body: { username, password },
        silent401: true,
      });
      setCsrfToken(data.csrfToken);
      queryClient.clear();
      setUser(data.user);
      return data.user;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      const data = await api<{ csrfToken: string }>("/auth/logout", { method: "POST", silent401: true });
      setCsrfToken(data.csrfToken);
    } finally {
      // Даже если запрос не прошёл, на этом устройстве личные данные больше не показываем.
      queryClient.clear();
      setUser(null);
    }
  }, [queryClient]);

  const value = useMemo(
    () => ({ user, loading, bootError, login, logout, retryBoot: () => setBootAttempt((n) => n + 1) }),
    [user, loading, bootError, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth вызван вне AuthProvider");
  return context;
}

export const homePath = (user: User) =>
  ({ student: "/today", teacher: "/teacher", dean_staff: "/staff", admin: "/staff" })[user.role];

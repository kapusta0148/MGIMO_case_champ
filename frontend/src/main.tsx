import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ApiError } from "./api/client";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "@fontsource-variable/onest";
import "@fontsource-variable/unbounded";
import "./index.css";
import { applyTheme, readTheme } from "./lib/theme";

applyTheme(readTheme());

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      // Повторяем только сбои сети и сервера; 401/403/404 — это ответ, а не сбой.
      retry: (count, error) => count < 2 && error instanceof ApiError && (error.status === 0 || error.status >= 500),
      refetchOnWindowFocus: true,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <AuthProvider>
            <App />
          </AuthProvider>
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);

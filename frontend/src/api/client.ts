// Единственная точка общения с сервером.
// Сессия живёт в HttpOnly-cookie (JS её не видит), CSRF-токен — в памяти вкладки.

export class ApiError extends Error {
  status: number;
  code: string;
  fields?: Record<string, string>;

  constructor(status: number, code: string, message: string, fields?: Record<string, string>) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

/** AuthProvider подписывается, чтобы при истёкшей сессии вернуть пользователя на вход. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function ensureCsrf(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await fetch("/api/auth/csrf", { credentials: "same-origin" });
  const data = (await response.json()) as { csrfToken: string };
  csrfToken = data.csrfToken;
  return csrfToken;
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  /** Не сообщать AuthProvider о 401 (например, при проверке «вошёл ли пользователь»). */
  silent401?: boolean;
};

export async function api<T>(path: string, options: Options = {}, retried = false): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  const init: RequestInit = { method, credentials: "same-origin", headers };

  let response: Response;
  try {
    if (method !== "GET") {
      headers["X-CSRF-Token"] = await ensureCsrf();
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body ?? {});
    }
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "network", "Нет связи с сервером. Проверьте интернет и повторите.");
  }

  const data = await response.json().catch(() => null);
  if (response.ok) return data as T;

  const error = data?.error ?? {};
  if (response.status === 403 && error.code === "csrf_failed" && !retried) {
    // Токен устарел (например, сессия обновилась в другой вкладке): берём новый и повторяем один раз.
    csrfToken = null;
    return api<T>(path, options, true);
  }
  if (response.status === 401 && !options.silent401) onUnauthorized?.();
  throw new ApiError(
    response.status,
    error.code ?? "http_error",
    error.message ?? "Запрос не выполнен. Попробуйте ещё раз.",
    error.fields,
  );
}

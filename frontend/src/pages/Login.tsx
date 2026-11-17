import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { homePath, useAuth } from "../auth/AuthContext";
import { Brand, PrototypeNote } from "../components/Layout";
import { Button } from "../components/ui";

export function LoginPage() {
  const { user, login } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});

  // Куда вернуть после входа: студент — на страницу, которую открывал (например, ссылку из уведомления).
  const from = (location.state as { from?: string } | null)?.from;
  // Переход делает только этот Navigate: он срабатывает и после успешного входа, без гонки с navigate().
  if (user) return <Navigate to={user.role === "student" && from?.startsWith("/") ? from : homePath(user)} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const local: Record<string, string> = {};
    if (!username.trim()) local.username = "Введите логин.";
    if (!password) local.password = "Введите пароль.";
    setFields(local);
    setError(null);
    if (Object.keys(local).length) return;

    setBusy(true);
    try {
      await login(username.trim(), password);
    } catch (caught) {
      const apiError = caught as ApiError;
      setFields(apiError.fields ?? {});
      setError(apiError.fields ? null : apiError.message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  const fieldClass =
    "mt-1.5 block min-h-12 w-full rounded-[14px] border border-line bg-surface px-3.5 text-base text-text outline-none transition-colors focus:border-accent-2";

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col justify-center px-4 py-8">
      <Brand />
      <h1 className="m-0 mt-8 font-display text-[26px] font-bold leading-tight tracking-tight">Вход в кабинет</h1>
      <p className="m-0 mt-1.5 text-sm text-muted">
        Расписание, оценки, заявки и сообщения деканата — в одном месте.
      </p>

      <form onSubmit={submit} noValidate className="mt-6 grid gap-4">
        <label className="text-sm font-semibold">
          Логин
          <input
            className={fieldClass}
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            aria-invalid={Boolean(fields.username)}
            aria-describedby={fields.username ? "username-error" : undefined}
          />
          {fields.username && (
            <span id="username-error" className="mt-1 block text-sm font-normal text-danger">
              {fields.username}
            </span>
          )}
        </label>
        <label className="text-sm font-semibold">
          Пароль
          <input
            className={fieldClass}
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={Boolean(fields.password)}
            aria-describedby={fields.password ? "password-error" : undefined}
          />
          {fields.password && (
            <span id="password-error" className="mt-1 block text-sm font-normal text-danger">
              {fields.password}
            </span>
          )}
        </label>

        {error && (
          <p role="alert" className="m-0 rounded-[14px] bg-danger-soft p-3 text-sm text-danger">
            {error}
          </p>
        )}
        <Button type="submit" busy={busy} className="min-h-12 text-base">
          Войти
        </Button>
      </form>

      <div className="mt-6 rounded-[18px] border border-line bg-surface/70 p-3.5 text-[13px] text-muted">
        <strong className="text-text">Демонстрационный вход.</strong> Используйте тестовые логин и пароль,
        выданные командой. Настоящие данные вуза здесь не нужны и не принимаются.
      </div>
      <PrototypeNote className="mt-6" />
    </main>
  );
}

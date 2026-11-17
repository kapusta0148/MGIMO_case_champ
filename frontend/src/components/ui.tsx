import { CircleAlert, Inbox, LoaderCircle, RefreshCw } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { ApiError } from "../api/client";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

const CARD = "mc-rise rounded-[20px] border bg-surface p-4";

export function Card({ children, className, tone }: { children: ReactNode; className?: string; tone?: "warn" }) {
  return <section className={cx(CARD, tone === "warn" ? "border-warn/50" : "border-line", className)}>{children}</section>;
}

/** Карточка-ссылка: вся площадь нажимается, высота не меньше 44 px. */
export function CardLink({ children, className, ...props }: LinkProps & { className?: string }) {
  return (
    <Link
      {...props}
      className={cx(
        CARD,
        "block min-h-11 border-line text-text no-underline transition-colors hover:border-accent/60 active:bg-surface-2",
        className,
      )}
    >
      {children}
    </Link>
  );
}

export const Kicker = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cx("text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted", className)}>{children}</div>
);

type Tone = "neutral" | "accent" | "cyan" | "warn" | "ok" | "danger";
const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  accent: "bg-accent-soft text-accent-text",
  cyan: "bg-accent-2/15 text-accent-2",
  warn: "bg-warn-soft text-warn",
  ok: "bg-ok-soft text-ok",
  danger: "bg-danger-soft text-danger",
};

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

export const STATUS_TONE: Record<string, Tone> = {
  submitted: "neutral",
  in_review: "cyan",
  needs_info: "warn",
  approved: "ok",
  rejected: "danger",
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost"; busy?: boolean };

export function Button({ variant = "primary", busy, children, className, disabled, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      disabled={disabled || busy}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 text-sm font-bold transition-[opacity,transform] active:scale-[0.98] disabled:opacity-60",
        variant === "primary" ? "mc-grad" : "border border-line bg-surface text-text hover:bg-surface-2",
        className,
      )}
    >
      {busy && <LoaderCircle size={16} className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function PageTitle({ title, subtitle, action }: { title: string; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <header className="mb-4 flex items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="m-0 font-display text-[22px] font-bold leading-tight tracking-tight">{title}</h1>
        {subtitle && <p className="m-0 mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid gap-3" role="status" aria-label="Загрузка">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={cx("mc-skeleton", i === 0 ? "h-40" : "h-24")} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const status = error instanceof ApiError ? error.status : -1;
  const message = error instanceof ApiError ? error.message : "Что-то пошло не так. Попробуйте ещё раз.";
  const title =
    status === 0 ? "Нет соединения" : status === 404 ? "Недоступно" : status === 403 ? "Нет доступа" : "Не удалось загрузить данные";
  return (
    <div role="alert" className="rounded-[20px] border border-danger/50 bg-danger-soft p-4 text-sm">
      <div className="flex items-start gap-2 font-semibold text-danger">
        <CircleAlert size={18} className="mt-0.5 shrink-0" aria-hidden />
        {title}
      </div>
      <p className="m-0 mt-1 text-text">{message}</p>
      {onRetry && (
        <Button variant="ghost" className="mt-3" onClick={onRetry}>
          <RefreshCw size={16} aria-hidden /> Повторить
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="rounded-[20px] border border-dashed border-line p-6 text-center">
      <Inbox className="mx-auto text-muted" size={28} aria-hidden />
      <p className="m-0 mt-2 font-semibold">{title}</p>
      {text && <p className="m-0 mt-1 text-sm text-muted">{text}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export { cx };

import { ArrowLeft, Check, Clock, Search, Send } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { useRequestTypes } from "../../api/hooks";
import { useStaffRequest, useStaffRequestAction, useStaffRequests, useStaffSummary } from "../../api/staffHooks";
import type { RequestStatus } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  Badge,
  Button,
  Card,
  CardLink,
  cx,
  EmptyState,
  ErrorState,
  Kicker,
  PageTitle,
  Skeleton,
  STATUS_TONE,
} from "../../components/ui";
import { dateTime, plural } from "../../lib/format";

const inputClass =
  "block min-h-11 w-full rounded-[14px] border border-line bg-surface px-3.5 text-base text-text outline-none transition-colors focus:border-accent-2";

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "open", label: "В работе" },
  { value: "submitted", label: "Новые" },
  { value: "in_review", label: "На рассмотрении" },
  { value: "needs_info", label: "Уточнение" },
  { value: "approved", label: "Одобрены" },
  { value: "rejected", label: "Отклонены" },
  { value: "all", label: "Все" },
];

function age(hours: number) {
  if (hours < 1) return "меньше часа";
  if (hours < 48) return `${hours} ${plural(hours, "час", "часа", "часов")}`;
  const days = Math.floor(hours / 24);
  return `${days} ${plural(days, "день", "дня", "дней")}`;
}

// ── Обзор ─────────────────────────────────────────────────────────────────────

export function StaffOverviewPage() {
  const { user } = useAuth();
  const { data, error, isPending, refetch } = useStaffSummary();
  if (isPending) return <Skeleton rows={3} />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;
  const tiles: { status: RequestStatus | "stale"; label: string; value: number; tone?: string }[] = [
    { status: "submitted", label: "Новые", value: data.counts.submitted },
    { status: "in_review", label: "На рассмотрении", value: data.counts.in_review },
    { status: "needs_info", label: "Ждут студента", value: data.counts.needs_info },
    { status: "stale", label: "Новые дольше суток", value: data.stale, tone: data.stale ? "text-warn" : "" },
  ];
  return (
    <div className="grid gap-3">
      <PageTitle
        title={`Здравствуйте, ${user?.fullName.split(" ")[1] ?? ""}`}
        subtitle={`Зона ответственности: ${data.faculties.map((f) => f.code).join(", ") || "не назначена"}`}
      />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((tile) => (
          <CardLink
            key={tile.status}
            to={`/staff/requests?status=${tile.status === "stale" ? "submitted" : tile.status}`}
            className="p-3.5"
          >
            <div className={cx("font-display text-[28px] font-bold leading-none tabular-nums", tile.tone)}>{tile.value}</div>
            <div className="mt-1.5 text-xs text-muted">{tile.label}</div>
          </CardLink>
        ))}
      </div>
      <Card>
        <Kicker>Скорость обработки</Kicker>
        <p className="m-0 mt-1.5 text-sm">
          {data.averageDecisionHours === null ? (
            "За последние 30 дней решений пока нет."
          ) : (
            <>
              Решено заявок: <b>{data.decidedLast30Days}</b>, в среднем за{" "}
              <b>{age(Math.round(data.averageDecisionHours))}</b>.
            </>
          )}
        </p>
        <p className="m-0 mt-1 text-xs text-muted">{data.explanation}</p>
      </Card>
      <Card>
        <Kicker>В работе по типам</Kicker>
        {data.openByType.length ? (
          <ul className="m-0 mt-2 grid list-none gap-1.5 p-0 text-sm">
            {data.openByType.map((row) => (
              <li key={row.type} className="flex justify-between gap-3">
                <Link to={`/staff/requests?type=${row.type}`} className="text-text">
                  {row.title}
                </Link>
                <b className="tabular-nums">{row.count}</b>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 mt-1.5 text-sm text-muted">Открытых заявок нет.</p>
        )}
      </Card>
    </div>
  );
}

// ── Очередь ───────────────────────────────────────────────────────────────────

export function StaffRequestsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "open";
  const type = params.get("type") || "";
  const [q, setQ] = useState(params.get("q") || "");
  const [debounced, setDebounced] = useState(q);
  const types = useRequestTypes();

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(q), 300);
    return () => clearTimeout(timer);
  }, [q]);

  const { data, error, isPending, isFetching, refetch } = useStaffRequests({ status, type, q: debounced });

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  return (
    <div>
      <PageTitle title="Заявки" subtitle="Очередь в пределах ваших факультетов" />
      <div className="mb-3 flex gap-1.5 overflow-x-auto pb-1" role="group" aria-label="Статус">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            aria-pressed={status === filter.value}
            onClick={() => set("status", filter.value === "open" ? "" : filter.value)}
            className={cx(
              "min-h-10 shrink-0 rounded-full border px-3.5 text-[13px] font-semibold",
              status === filter.value ? "mc-tab-active border-transparent" : "border-line bg-surface text-muted",
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>
      <div className="mb-4 grid gap-2 sm:grid-cols-[1fr_220px]">
        <label className="relative block">
          <span className="sr-only">Поиск по номеру, теме или ФИО</span>
          <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
          <input
            className={cx(inputClass, "pl-10")}
            type="search"
            placeholder="Номер, тема или ФИО"
            value={q}
            maxLength={80}
            onChange={(e) => {
              setQ(e.target.value);
              set("q", e.target.value);
            }}
          />
        </label>
        <label>
          <span className="sr-only">Тип заявки</span>
          <select className={inputClass} value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">Все типы</option>
            {types.data?.map((t) => (
              <option key={t.type} value={t.type}>
                {t.title}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isPending ? (
        <Skeleton />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState title="Заявок не найдено" text="Измените фильтр или строку поиска." />
      ) : (
        <div className={cx("grid gap-2 transition-opacity", isFetching && "opacity-70")}>
          {data.map((item) => (
            <CardLink key={item.id} to={`/staff/requests/${item.id}`} className="p-3.5">
              <div className="flex items-start justify-between gap-2">
                <p className="m-0 font-semibold leading-snug">{item.title}</p>
                <Badge tone={STATUS_TONE[item.status]}>{item.statusLabel}</Badge>
              </div>
              <p className="m-0 mt-1 text-[13px] text-muted">
                {item.owner.name} · {item.owner.group}
              </p>
              <p className="m-0 mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <span>{item.number}</span>
                <span>подана {dateTime(item.createdAt)}</span>
                {!item.isFinal && (
                  <span className={cx("inline-flex items-center gap-1", item.isStale && "font-semibold text-warn")}>
                    <Clock size={12} aria-hidden /> ждёт {age(item.hoursOpen)}
                  </span>
                )}
              </p>
            </CardLink>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Карточка заявки ───────────────────────────────────────────────────────────

export function StaffRequestPage() {
  const id = Number(useParams().id);
  const { data, error, isPending, refetch } = useStaffRequest(id);
  const action = useStaffRequestAction(id);
  const [comment, setComment] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (isPending) return <Skeleton />;
  if (error || !data)
    return (
      <div>
        <Link to="/staff/requests" className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent-text no-underline">
          <ArrowLeft size={16} aria-hidden /> Очередь заявок
        </Link>
        <ErrorState error={error} onRetry={(error as ApiError)?.status === 404 ? undefined : () => void refetch()} />
      </div>
    );

  async function run(input: Parameters<typeof action.mutateAsync>[0], message: string) {
    setFieldError(null);
    setDone(null);
    try {
      await action.mutateAsync(input);
      setComment("");
      setDone(message);
    } catch (caught) {
      const apiError = caught as ApiError;
      setFieldError(apiError.fields?.comment ?? apiError.fields?.toStatus ?? apiError.message);
    }
  }

  function submitComment(event: FormEvent) {
    event.preventDefault();
    void run({ kind: "comment", comment }, "Комментарий отправлен.");
  }

  return (
    <div className="grid gap-3">
      <div>
        <Link to="/staff/requests" className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent-text no-underline">
          <ArrowLeft size={16} aria-hidden /> Очередь заявок
        </Link>
        <PageTitle title={data.title} subtitle={`${data.number} · подана ${dateTime(data.createdAt)}`} />
        {done && (
          <p role="status" className="m-0 flex items-center gap-1.5 rounded-[14px] bg-ok-soft p-3 text-sm font-semibold text-ok">
            <Check size={16} aria-hidden /> {done} Студент получил уведомление.
          </p>
        )}
      </div>

      <Card>
        <div className="flex items-center justify-between gap-2">
          <Kicker>Студент</Kicker>
          <Badge tone={STATUS_TONE[data.status]}>{data.statusLabel}</Badge>
        </div>
        <p className="m-0 mt-1.5 font-semibold">{data.owner.name}</p>
        <p className="m-0 text-[13px] text-muted">
          {data.owner.group} · {data.owner.year} курс · {data.owner.program} · зачётка {data.owner.recordBook}
        </p>
      </Card>

      <Card>
        <Kicker>Данные заявки</Kicker>
        <dl className="m-0 mt-2 grid gap-2 text-sm">
          {data.details.map((row) => (
            <div key={row.key} className="flex justify-between gap-4">
              <dt className="text-muted">{row.label}</dt>
              <dd className="m-0 text-right font-medium">{row.value}</dd>
            </div>
          ))}
        </dl>
        {data.comment && (
          <p className="m-0 mt-3 whitespace-pre-wrap break-words rounded-[14px] bg-surface-2 p-3 text-sm">{data.comment}</p>
        )}
      </Card>

      {(data.allowedTransitions.length > 0 || data.canComment) && (
        <Card className="border-accent/50">
          <Kicker>Решение</Kicker>
          <label htmlFor="staff-comment" className="mt-2 block text-sm font-semibold">
            Комментарий студенту
            <textarea
              id="staff-comment"
              rows={3}
              maxLength={1000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className={cx(inputClass, "mt-1.5 py-3")}
              placeholder="Например: справка готова, кабинет 2010"
            />
          </label>
          <p className="m-0 mt-1 text-xs text-muted">Для «Отклонить» и «Запросить уточнение» комментарий обязателен.</p>
          {fieldError && (
            <p role="alert" className="m-0 mt-2 text-sm text-danger">
              {fieldError}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {data.allowedTransitions.map((t) => (
              <Button
                key={t.status}
                variant={t.status === "approved" || t.status === "in_review" ? "primary" : "ghost"}
                busy={action.isPending}
                onClick={() =>
                  void run({ kind: "transition", toStatus: t.status, comment }, `Статус изменён: ${t.label.toLowerCase()}.`)
                }
              >
                {{ in_review: "Взять в работу", approved: "Одобрить", rejected: "Отклонить", needs_info: "Запросить уточнение" }[
                  t.status as string
                ] ?? t.label}
              </Button>
            ))}
            {data.canComment && (
              <form onSubmit={submitComment}>
                <Button type="submit" variant="ghost" busy={action.isPending} disabled={!comment.trim()}>
                  <Send size={15} aria-hidden /> Только комментарий
                </Button>
              </form>
            )}
          </div>
        </Card>
      )}

      <Card>
        <Kicker>История</Kicker>
        <ol className="m-0 mt-2 grid list-none gap-3 p-0 text-sm">
          {data.events.map((event) => (
            <li key={event.id} className="border-l-2 border-accent/40 pl-3">
              <p className="m-0 font-semibold">{event.kind === "comment" ? "Комментарий" : event.toStatusLabel}</p>
              <p className="m-0 text-xs text-muted">
                {dateTime(event.createdAt)} · {event.actor.isMe ? "вы" : event.actor.label}
              </p>
              {event.comment && <p className="m-0 mt-1 whitespace-pre-wrap break-words">{event.comment}</p>}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

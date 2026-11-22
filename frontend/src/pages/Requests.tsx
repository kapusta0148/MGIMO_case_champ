import { ArrowLeft, Check, Plus, Send } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useCommentRequest, useCreateRequest, useRequest, useRequests, useRequestTypes } from "../api/hooks";
import type { RequestField, RequestStep, RequestType } from "../api/types";
import { Badge, Button, Card, CardLink, cx, EmptyState, ErrorState, Kicker, PageTitle, Skeleton, STATUS_TONE } from "../components/ui";
import { dateTime } from "../lib/format";

const inputClass =
  "mt-1.5 block min-h-12 w-full rounded-[14px] border border-line bg-surface px-3.5 text-base text-text outline-none transition-colors focus:border-accent-2";

const BackLink = ({ to, children }: { to: string; children: string }) => (
  <Link to={to} className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent-text no-underline">
    <ArrowLeft size={16} aria-hidden /> {children}
  </Link>
);

function Steps({ steps }: { steps: RequestStep[] }) {
  return (
    <ol className="m-0 mt-3 grid list-none grid-cols-3 gap-2 p-0">
      {steps.map((step) => (
        <li key={step.key} className="text-xs">
          <span className={cx("mb-1.5 block h-1.5 rounded-full", step.done ? "mc-grad" : "bg-surface-2")} />
          <span className={step.done ? "font-semibold" : "text-muted"}>{step.label}</span>
        </li>
      ))}
    </ol>
  );
}

// ── Список ────────────────────────────────────────────────────────────────────

export function RequestsPage() {
  const { data, error, isPending, refetch } = useRequests();
  const newButton = (
    <Link
      to="/requests/new"
      className="mc-grad inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-xl px-4 text-sm font-bold no-underline"
    >
      <Plus size={16} aria-hidden /> Новая
    </Link>
  );
  return (
    <div>
      <PageTitle title="Заявки" subtitle="Справки и заявления в деканат" action={newButton} />
      {isPending ? (
        <Skeleton />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState
          title="Заявок пока нет"
          text="Закажите справку или подайте заявление — статус появится здесь."
          action={newButton}
        />
      ) : (
        <div className="grid gap-2">
          {data.map((item) => (
            <CardLink key={item.id} to={`/requests/${item.id}`} className="text-text">
              <div className="flex items-start justify-between gap-2">
                <p className="m-0 font-semibold leading-snug">{item.title}</p>
                <Badge tone={STATUS_TONE[item.status]}>{item.statusLabel}</Badge>
              </div>
              <p className="m-0 mt-1 text-sm text-muted">
                {item.number} · подана {dateTime(item.createdAt)}
              </p>
            </CardLink>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Новая заявка ──────────────────────────────────────────────────────────────

type Draft = { type: string | null; fields: Record<string, string>; comment: string; key: string };
const DRAFT_KEY = "mc.request-draft";
const newKey = () => crypto.randomUUID();

function loadDraft(): Draft {
  try {
    const saved = sessionStorage.getItem(DRAFT_KEY);
    if (saved) return JSON.parse(saved) as Draft;
  } catch {
    /* повреждённый черновик игнорируем */
  }
  return { type: null, fields: {}, comment: "", key: newKey() };
}

function FieldInput({
  field,
  value,
  error,
  onChange,
}: {
  field: RequestField;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const id = `field-${field.key}`;
  const common = {
    id,
    value,
    "aria-invalid": Boolean(error),
    "aria-describedby": error ? `${id}-error` : undefined,
    className: inputClass,
  };
  return (
    <label htmlFor={id} className="block text-sm font-semibold">
      {field.label}
      {field.kind === "select" ? (
        <select {...common} onChange={(e) => onChange(e.target.value)}>
          <option value="">Выберите…</option>
          {field.options!.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          {...common}
          type={field.kind === "text" ? "text" : field.kind}
          inputMode={field.kind === "number" ? "numeric" : undefined}
          min={field.min}
          max={field.max}
          maxLength={field.maxLength}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {error && (
        <span id={`${id}-error`} className="mt-1 block text-sm font-normal text-danger">
          {error}
        </span>
      )}
    </label>
  );
}

export function RequestNewPage() {
  const navigate = useNavigate();
  const types = useRequestTypes();
  const create = useCreateRequest();
  const [draft, setDraft] = useState<Draft>(loadDraft);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  // Черновик переживает случайное обновление страницы (хранится только в этой вкладке).
  useEffect(() => {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  }, [draft]);

  const spec: RequestType | undefined = useMemo(
    () => types.data?.find((t) => t.type === draft.type),
    [types.data, draft.type],
  );

  function choose(type: RequestType) {
    const fields: Record<string, string> = {};
    for (const field of type.fields) if (field.default !== undefined) fields[field.key] = String(field.default);
    setDraft({ type: type.type, fields, comment: "", key: newKey() });
    setErrors({});
    setFormError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!spec) return;
    const local: Record<string, string> = {};
    for (const field of spec.fields)
      if (field.required && !draft.fields[field.key]?.trim()) local[field.key] = "Заполните это поле.";
    if (spec.commentRequired && draft.comment.trim().length < 10)
      local.comment = "Опишите ситуацию подробнее (от 10 символов).";
    setErrors(local);
    setFormError(null);
    if (Object.keys(local).length) return;

    const fields: Record<string, string | number> = {};
    for (const field of spec.fields) {
      const value = draft.fields[field.key];
      if (value !== undefined && value !== "") fields[field.key] = field.kind === "number" ? Number(value) : value;
    }
    try {
      const result = await create.mutateAsync({
        payload: { type: spec.type, fields, comment: draft.comment },
        idempotencyKey: draft.key,
      });
      sessionStorage.removeItem(DRAFT_KEY);
      navigate(`/requests/${result.request.id}`, { replace: true, state: { justCreated: true } });
    } catch (caught) {
      const apiError = caught as ApiError;
      setErrors(apiError.fields ?? {});
      setFormError(apiError.fields ? "Проверьте отмеченные поля." : apiError.message);
    }
  }

  if (types.isPending) return <Skeleton />;
  if (types.error) return <ErrorState error={types.error} onRetry={() => void types.refetch()} />;

  if (!spec) {
    return (
      <div>
        <BackLink to="/requests">Все заявки</BackLink>
        <PageTitle title="Новая заявка" subtitle="Что нужно оформить?" />
        <div className="grid gap-2">
          {types.data.map((type) => (
            <button
              key={type.type}
              onClick={() => choose(type)}
              className="mc-rise min-h-11 rounded-[20px] border border-line bg-surface p-4 text-left text-text transition-colors hover:border-accent/60"
            >
              <span className="block font-semibold">{type.title}</span>
              <span className="mt-0.5 block text-sm text-muted">{type.description}</span>
              <span className="mt-1.5 block text-xs text-muted">Срок: {type.eta}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => setDraft({ type: null, fields: {}, comment: "", key: newKey() })}
        className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent-text"
      >
        <ArrowLeft size={16} aria-hidden /> Другой тип заявки
      </button>
      <PageTitle title={spec.title} subtitle={`${spec.description} Срок: ${spec.eta}.`} />
      <form onSubmit={submit} noValidate className="grid gap-4">
        {spec.fields.map((field) => (
          <FieldInput
            key={field.key}
            field={field}
            value={draft.fields[field.key] ?? ""}
            error={errors[field.key]}
            onChange={(value) => setDraft((d) => ({ ...d, fields: { ...d.fields, [field.key]: value } }))}
          />
        ))}
        <label htmlFor="comment" className="block text-sm font-semibold">
          Комментарий {spec.commentRequired ? "" : "(необязательно)"}
          <textarea
            id="comment"
            rows={4}
            maxLength={1000}
            value={draft.comment}
            onChange={(e) => setDraft((d) => ({ ...d, comment: e.target.value }))}
            aria-invalid={Boolean(errors.comment)}
            className={cx(inputClass, "py-3")}
          />
          <span className="mt-1 flex justify-between text-xs font-normal text-muted">
            <span className="text-sm text-danger">{errors.comment}</span>
            {draft.comment.length}/1000
          </span>
        </label>
        {formError && (
          <p role="alert" className="m-0 rounded-xl bg-danger-soft p-3 text-sm text-danger">
            {formError}
          </p>
        )}
        <Button type="submit" busy={create.isPending} className="min-h-12 text-base">
          <Send size={16} aria-hidden /> Отправить заявку
        </Button>
      </form>
    </div>
  );
}

// ── Подробности ───────────────────────────────────────────────────────────────

export function RequestDetailPage() {
  const id = Number(useParams().id);
  const location = useLocation();
  const justCreated = Boolean((location.state as { justCreated?: boolean } | null)?.justCreated);
  const { data, error, isPending, refetch } = useRequest(id);
  const comment = useCommentRequest(id);
  const [text, setText] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);

  if (!Number.isInteger(id)) return <ErrorState error={new ApiError(404, "not_found", "Заявка не найдена.")} />;
  if (isPending) return <Skeleton />;
  if (error || !data)
    return (
      <div>
        <BackLink to="/requests">Все заявки</BackLink>
        <ErrorState error={error} onRetry={(error as ApiError)?.status === 404 ? undefined : () => void refetch()} />
      </div>
    );

  async function send(event: FormEvent) {
    event.preventDefault();
    setCommentError(null);
    if (!text.trim()) return setCommentError("Напишите комментарий.");
    try {
      await comment.mutateAsync(text);
      setText("");
    } catch (caught) {
      const apiError = caught as ApiError;
      setCommentError(apiError.fields?.comment ?? apiError.message);
    }
  }

  return (
    <div className="grid gap-3">
      <div>
        <BackLink to="/requests">Все заявки</BackLink>
        {justCreated && (
          <p role="status" className="m-0 mb-3 flex items-center gap-2 rounded-xl bg-ok-soft p-3 text-sm font-semibold text-ok">
            <Check size={16} aria-hidden /> Заявка отправлена. Статус будет обновляться здесь и в уведомлениях.
          </p>
        )}
        <PageTitle title={data.title} subtitle={`${data.number} · подана ${dateTime(data.createdAt)}`} />
      </div>

      <Card tone={data.status === "needs_info" ? "warn" : undefined}>
        <div className="flex items-center justify-between gap-2">
          <Kicker>Статус</Kicker>
          <Badge tone={STATUS_TONE[data.status]}>{data.statusLabel}</Badge>
        </div>
        <Steps steps={data.steps} />
        {!data.isFinal && data.eta && <p className="m-0 mt-3 text-sm text-muted">Срок рассмотрения: {data.eta}.</p>}
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
        {data.comment && <p className="m-0 mt-3 whitespace-pre-wrap break-words rounded-xl bg-surface-2 p-3 text-sm">{data.comment}</p>}
      </Card>

      <Card>
        <Kicker>История</Kicker>
        <ol className="m-0 mt-2 grid list-none gap-3 p-0 text-sm">
          {data.events.map((event) => (
            <li key={event.id} className="border-l-2 border-accent/40 pl-3">
              <p className="m-0 font-semibold">
                {event.kind === "comment" ? "Комментарий" : event.toStatusLabel}
              </p>
              <p className="m-0 text-xs text-muted">
                {dateTime(event.createdAt)} · {event.actor.isMe ? "вы" : event.actor.label}
              </p>
              {event.comment && <p className="m-0 mt-1 whitespace-pre-wrap break-words">{event.comment}</p>}
            </li>
          ))}
        </ol>
      </Card>

      {data.canComment && (
        <form onSubmit={send} noValidate>
          <label htmlFor="reply" className="block text-sm font-semibold">
            {data.status === "needs_info" ? "Ответ деканату" : "Добавить комментарий"}
            <textarea
              id="reply"
              rows={3}
              maxLength={1000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              className={cx(inputClass, "py-3")}
            />
          </label>
          {commentError && (
            <p role="alert" className="m-0 mt-1 text-sm text-danger">
              {commentError}
            </p>
          )}
          <Button type="submit" busy={comment.isPending} className="mt-3 w-full">
            Отправить
          </Button>
        </form>
      )}
    </div>
  );
}

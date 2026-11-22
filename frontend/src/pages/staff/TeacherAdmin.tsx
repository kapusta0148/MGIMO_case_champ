import { ArrowLeft, Check, Lock } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import {
  useAdminUsers,
  useAuditLog,
  useSetUserActive,
  useTeacherCourses,
  useTeacherSheet,
  useUpdateAssessment,
} from "../../api/staffHooks";
import type { TeacherAssessment } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Badge, Button, Card, CardLink, cx, EmptyState, ErrorState, Kicker, PageTitle, Skeleton } from "../../components/ui";
import { dateTime, dayMonth } from "../../lib/format";

// ── Преподаватель: курсы ──────────────────────────────────────────────────────

export function TeacherCoursesPage() {
  const { data, error, isPending, refetch } = useTeacherCourses();
  if (isPending) return <Skeleton />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <div>
      <PageTitle title="Мои курсы" subtitle="Только дисциплины и группы, закреплённые за вами" />
      {data.length === 0 ? (
        <EmptyState title="Закреплённых курсов нет" />
      ) : (
        <div className="grid gap-2">
          {data.map((course) => (
            <CardLink key={course.id} to={`/teacher/courses/${course.id}`}>
              <div className="flex items-start justify-between gap-2">
                <p className="m-0 font-semibold leading-snug">{course.subject}</p>
                <Badge tone={course.isCurrent ? "cyan" : "neutral"}>{course.isCurrent ? "текущий" : "архив"}</Badge>
              </div>
              <p className="m-0 mt-1 text-[13px] text-muted">
                Группа {course.group} · {course.controlFormLabel} · студентов: {course.students} · {course.term}
              </p>
            </CardLink>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Преподаватель: ведомость ──────────────────────────────────────────────────

function ScoreCell({ item, courseId, editable }: { item: TeacherAssessment; courseId: number; editable: boolean }) {
  const update = useUpdateAssessment(courseId);
  const [value, setValue] = useState(item.score === null ? "" : String(item.score));
  const [state, setState] = useState<"idle" | "saved" | "error">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Новые данные с сервера не перетирают то, что преподаватель сейчас вводит.
    if (document.activeElement !== inputRef.current) setValue(item.score === null ? "" : String(item.score));
  }, [item.score]);
  const [error, setError] = useState<string | null>(null);
  const label = item.kind === "final" ? "Итог" : item.title;

  async function save() {
    const next = value.trim() === "" ? null : Number(value);
    if (next === item.score) return;
    setError(null);
    try {
      await update.mutateAsync({ id: item.id, score: next });
      setState("saved");
    } catch (caught) {
      setState("error");
      setError((caught as ApiError).fields?.score ?? (caught as ApiError).message);
    }
  }

  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
      <span className="min-w-0 text-sm">
        {label}
        {item.date && <span className="text-muted"> · {dayMonth(item.date)}</span>}
      </span>
      <span className="flex items-center gap-2">
        {state === "saved" && <Check size={16} className="text-ok" aria-label="сохранено" />}
        <input
          ref={inputRef}
          aria-label={`${label}: балл из 100`}
          inputMode="numeric"
          disabled={!editable || update.isPending}
          value={value}
          placeholder="—"
          onChange={(e) => {
            setValue(e.target.value.replace(/[^0-9]/g, "").slice(0, 3));
            setState("idle");
          }}
          onBlur={() => void save()}
          onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
          className={cx(
            "h-11 w-16 rounded-[12px] border bg-surface text-center font-display text-[15px] font-semibold tabular-nums text-text outline-none focus:border-accent-2 disabled:opacity-60",
            state === "error" ? "border-danger" : "border-line",
          )}
        />
      </span>
      {error && <span className="col-span-2 text-right text-[13px] text-danger">{error}</span>}
    </li>
  );
}

export function TeacherCoursePage() {
  const id = Number(useParams().id);
  const { data, error, isPending, refetch } = useTeacherSheet(id);
  const back = (
    <Link to="/teacher" className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent-text no-underline">
      <ArrowLeft size={16} aria-hidden /> Мои курсы
    </Link>
  );
  if (isPending) return <Skeleton />;
  if (error || !data)
    return (
      <div>
        {back}
        <ErrorState error={error} onRetry={(error as ApiError)?.status === 404 ? undefined : () => void refetch()} />
      </div>
    );

  return (
    <div className="grid gap-3">
      <div>
        {back}
        <PageTitle title={data.course.subject} subtitle={`Группа ${data.course.group} · ${data.course.controlFormLabel} · ${data.course.term}`} />
      </div>
      {data.editable ? (
        <p className="m-0 text-[13px] text-muted">
          Балл от 0 до 100 сохраняется, когда вы уходите из поля. Пустое поле — «ожидается». Студент получит уведомление,
          изменение попадёт в журнал.
        </p>
      ) : (
        <p className="m-0 flex items-center gap-1.5 rounded-[14px] bg-surface-2 p-3 text-sm text-muted">
          <Lock size={15} aria-hidden /> Ведомость прошлого семестра закрыта для изменений.
        </p>
      )}
      {data.students.map((student) => (
        <Card key={student.userId}>
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="m-0 font-semibold">{student.name}</p>
              <p className="m-0 text-xs text-muted">Зачётка {student.recordBook}</p>
            </div>
            <div className="text-right">
              <div className="font-display text-xl font-semibold tabular-nums">{student.currentScore ?? "—"}</div>
              <div className="text-[11px] text-muted">текущий рейтинг</div>
            </div>
          </div>
          <ul className="m-0 mt-3 grid list-none gap-2 p-0">
            {student.controls.map((item) => (
              <ScoreCell key={item.id} item={item} courseId={id} editable={data.editable} />
            ))}
            {student.final && (
              <ScoreCell key={student.final.id} item={student.final} courseId={id} editable={data.editable} />
            )}
          </ul>
          {student.finalResult && (
            <p className="m-0 mt-2 text-right text-[13px] text-muted">Итог: {student.finalResult.label}</p>
          )}
        </Card>
      ))}
    </div>
  );
}

// ── Администратор ─────────────────────────────────────────────────────────────

export function AdminUsersPage() {
  const { user: me } = useAuth();
  const { data, error, isPending, refetch } = useAdminUsers();
  const setActive = useSetUserActive();
  const [message, setMessage] = useState<string | null>(null);
  if (isPending) return <Skeleton />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <div>
      <PageTitle title="Демо-аккаунты" subtitle="Пароли не показываются и не меняются здесь" />
      {message && (
        <p role="alert" className="m-0 mb-3 text-sm text-danger">
          {message}
        </p>
      )}
      <div className="grid gap-2">
        {data.map((u) => (
          <Card key={u.id} className={cx("p-3.5", !u.isActive && "opacity-70")}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="m-0 font-semibold leading-snug">{u.fullName}</p>
                <p className="m-0 text-[13px] text-muted">
                  {u.username} · {u.roleLabel}
                  {u.detail && ` · ${u.detail}`}
                </p>
                <p className="m-0 mt-1 text-xs text-muted">
                  Последний вход: {u.lastLoginAt ? dateTime(u.lastLoginAt) : "не было"}
                </p>
              </div>
              <Badge tone={u.isActive ? "ok" : "danger"}>{u.isActive ? "активен" : "отключён"}</Badge>
            </div>
            {u.id !== me?.id && (
              <Button
                variant="ghost"
                className="mt-2.5"
                busy={setActive.isPending && setActive.variables?.id === u.id}
                onClick={() => {
                  setMessage(null);
                  setActive.mutate(
                    { id: u.id, isActive: !u.isActive },
                    { onError: (e) => setMessage((e as ApiError).message) },
                  );
                }}
              >
                {u.isActive ? "Отключить" : "Включить"}
              </Button>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}

function describe(value: Record<string, unknown> | null) {
  if (!value) return "";
  return Object.entries(value)
    .map(([k, v]) => `${k}: ${typeof v === "string" && /T\d\d:\d\d/.test(v) ? dateTime(v) : String(v)}`)
    .join(", ");
}

export function AdminAuditPage() {
  const { data, error, isPending, refetch } = useAuditLog();
  if (isPending) return <Skeleton />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return (
    <div>
      <PageTitle title="Журнал действий" subtitle="Последние 100 изменений сотрудников" />
      {data.length === 0 ? (
        <EmptyState title="Изменений пока не было" />
      ) : (
        <ol className="m-0 grid list-none gap-2 p-0">
          {data.map((e) => (
            <li key={e.id} className="rounded-[18px] border border-line bg-surface p-3.5 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <b>{e.actionLabel}</b>
                <span className="text-xs text-muted">{dateTime(e.createdAt)}</span>
              </div>
              <p className="m-0 mt-0.5 text-[13px] text-muted">
                {e.actor.name} · {e.entityType} №{e.entityId}
              </p>
              {(e.before || e.after) && (
                <p className="m-0 mt-1.5 break-words text-[13px]">
                  {e.before && <s className="text-muted">{describe(e.before)}</s>}
                  {e.before && e.after && " → "}
                  {e.after && <span>{describe(e.after)}</span>}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
      <Kicker className="mt-4">Записи создаёт сервер; пароли и содержимое файлов в журнал не попадают.</Kicker>
    </div>
  );
}

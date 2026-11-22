import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { useLessonAction, useStaffAnnouncements, useStaffGroups, useStaffSchedule, useStaffSummary } from "../../api/staffHooks";
import { useCreateAnnouncement, type LessonAction } from "../../api/staffHooks";
import type { Lesson, StaffSchedule } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { LessonCard } from "../../components/LessonCard";
import { Badge, Button, Card, cx, EmptyState, ErrorState, Kicker, PageTitle, Skeleton } from "../../components/ui";
import { addDays, dateTime, dayMonth, fullDate, time } from "../../lib/format";

const inputClass =
  "mt-1.5 block min-h-11 w-full rounded-[14px] border border-line bg-surface px-3.5 text-base text-text outline-none transition-colors focus:border-accent-2";

// ── Изменение занятия ─────────────────────────────────────────────────────────

function LessonEditor({ lesson, slots, onDone }: { lesson: Lesson; slots: StaffSchedule["pairSlots"]; onDone: (m: string) => void }) {
  const action = useLessonAction();
  const [date, setDate] = useState(lesson.date);
  const [start, setStart] = useState(time(lesson.startsAt));
  const [end, setEnd] = useState(time(lesson.endsAt));
  const [room, setRoom] = useState(lesson.room);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  async function run(body: LessonAction, label: string) {
    setErrors({});
    setMessage(null);
    try {
      const result = await action.mutateAsync({ id: lesson.id, body });
      onDone(`${label}. Уведомлено студентов: ${result.notified}.`);
    } catch (caught) {
      const apiError = caught as ApiError;
      setErrors(apiError.fields ?? {});
      setMessage(apiError.fields ? "Проверьте отмеченные поля." : apiError.message);
    }
  }

  function move(event: FormEvent) {
    event.preventDefault();
    void run({ action: "move", date, startTime: start, endTime: end, room, reason }, "Занятие перенесено");
  }

  const fieldError = (key: string) =>
    errors[key] && <span className="mt-1 block text-[13px] font-normal text-danger">{errors[key]}</span>;

  return (
    <form onSubmit={move} noValidate className="mt-2 grid gap-3 rounded-[18px] border border-accent/40 bg-surface-2 p-3.5">
      <div className="grid grid-cols-2 gap-3">
        <label className="col-span-2 text-sm font-semibold sm:col-span-1">
          Дата
          <input type="date" className={inputClass} value={date} onChange={(e) => setDate(e.target.value)} />
          {fieldError("date")}
        </label>
        <label className="col-span-2 text-sm font-semibold sm:col-span-1">
          Пара
          <select
            className={inputClass}
            value={slots.find((s) => s.start === start && s.end === end)?.number ?? ""}
            onChange={(e) => {
              const slot = slots.find((s) => s.number === Number(e.target.value));
              if (slot) {
                setStart(slot.start);
                setEnd(slot.end);
              }
            }}
          >
            <option value="">Своё время</option>
            {slots.map((s) => (
              <option key={s.number} value={s.number}>
                {s.number} пара, {s.start}–{s.end}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-semibold">
          Начало
          <input type="time" className={inputClass} value={start} onChange={(e) => setStart(e.target.value)} />
          {fieldError("startTime") || fieldError("startsAt")}
        </label>
        <label className="text-sm font-semibold">
          Конец
          <input type="time" className={inputClass} value={end} onChange={(e) => setEnd(e.target.value)} />
          {fieldError("endTime") || fieldError("endsAt")}
        </label>
        <label className="text-sm font-semibold">
          Аудитория
          <input className={inputClass} value={room} maxLength={40} onChange={(e) => setRoom(e.target.value)} />
          {fieldError("room")}
        </label>
        <label className="text-sm font-semibold">
          Причина
          <input
            className={inputClass}
            value={reason}
            maxLength={300}
            placeholder="Для студентов"
            onChange={(e) => setReason(e.target.value)}
          />
          {fieldError("reason")}
        </label>
      </div>
      {message && (
        <p role="alert" className="m-0 text-sm text-danger">
          {message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" busy={action.isPending}>
          Перенести
        </Button>
        {lesson.status !== "cancelled" && (
          <Button
            type="button"
            variant="ghost"
            busy={action.isPending}
            onClick={() => void run({ action: "cancel", reason }, "Занятие отменено")}
          >
            Отменить занятие
          </Button>
        )}
        {lesson.change && (
          <Button
            type="button"
            variant="ghost"
            busy={action.isPending}
            onClick={() => void run({ action: "restore" }, "Занятие возвращено в расписание")}
          >
            Вернуть как было
          </Button>
        )}
      </div>
      <p className="m-0 text-xs text-muted">
        Изменение сразу видно студентам группы в расписании, на «Сегодня» и в уведомлении.
      </p>
    </form>
  );
}

export function StaffSchedulePage() {
  const groups = useStaffGroups();
  const [groupId, setGroupId] = useState<number | null>(null);
  const [from, setFrom] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (groupId === null && groups.data?.length) setGroupId(groups.data[0].id);
  }, [groups.data, groupId]);

  const schedule = useStaffSchedule(groupId, from);
  if (groups.isPending) return <Skeleton />;
  if (groups.error) return <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />;
  if (!groups.data.length) return <EmptyState title="Нет групп в вашей зоне ответственности" />;
  const data = schedule.data;

  return (
    <div>
      <PageTitle title="Расписание групп" subtitle="Перенос, отмена и возврат занятий" />
      <label className="mb-3 block text-sm font-semibold">
        Группа
        <select
          className={inputClass}
          value={groupId ?? ""}
          onChange={(e) => {
            setGroupId(Number(e.target.value));
            setEditing(null);
          }}
        >
          {groups.data.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} · {g.faculty}, {g.year} курс · студентов: {g.students}
            </option>
          ))}
        </select>
      </label>

      {notice && (
        <p role="status" className="m-0 mb-3 flex items-center gap-1.5 rounded-[14px] bg-ok-soft p-3 text-sm font-semibold text-ok">
          <Check size={16} aria-hidden /> {notice}
        </p>
      )}

      {schedule.isPending ? (
        <Skeleton rows={4} />
      ) : schedule.error || !data ? (
        <ErrorState error={schedule.error} onRetry={() => void schedule.refetch()} />
      ) : (
        <>
          <div className="mb-3 flex items-center justify-between gap-2">
            <button
              aria-label="Предыдущая неделя"
              onClick={() => setFrom(addDays(data.from, -7))}
              className="grid size-11 place-items-center rounded-[13px] border border-line bg-surface text-text"
            >
              <ChevronLeft size={18} aria-hidden />
            </button>
            <span className="text-sm font-semibold">
              {dayMonth(data.from)} — {dayMonth(data.to)}
            </span>
            <button
              aria-label="Следующая неделя"
              onClick={() => setFrom(addDays(data.from, 7))}
              className="grid size-11 place-items-center rounded-[13px] border border-line bg-surface text-text"
            >
              <ChevronRight size={18} aria-hidden />
            </button>
          </div>
          <div className="grid gap-5">
            {data.days
              .filter((day) => day.lessons.length > 0)
              .map((day) => (
                <section key={day.date} aria-label={fullDate(day.date)}>
                  <h2 className="m-0 mb-2 flex items-center gap-2 text-sm font-bold first-letter:uppercase">
                    {fullDate(day.date)} {day.isToday && <Badge tone="cyan">сегодня</Badge>}
                  </h2>
                  <div className="grid gap-2">
                    {day.lessons.map((lesson) => (
                      <div key={lesson.id}>
                        <LessonCard lesson={lesson} />
                        {editing === lesson.id ? (
                          <LessonEditor
                            lesson={lesson}
                            slots={data.pairSlots}
                            onDone={(message) => {
                              setNotice(message);
                              setEditing(null);
                            }}
                          />
                        ) : (
                          day.date >= data.today && (
                            <button
                              onClick={() => {
                                setEditing(lesson.id);
                                setNotice(null);
                              }}
                              className="mt-1 min-h-10 px-1 text-sm font-semibold text-accent-text"
                            >
                              Изменить занятие
                            </button>
                          )
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Объявления ────────────────────────────────────────────────────────────────

export function StaffAnnouncementsPage() {
  const { user } = useAuth();
  const list = useStaffAnnouncements();
  const summary = useStaffSummary();
  const groups = useStaffGroups();
  const create = useCreateAnnouncement();
  const [audience, setAudience] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setErrors({});
    setMessage(null);
    const [kind, value] = audience.split(":");
    const payload: Record<string, unknown> = { title, body, audience: kind || undefined };
    if (kind === "faculty") payload.faculty = value;
    if (kind === "group") payload.groupId = Number(value);
    try {
      const result = await create.mutateAsync(payload);
      setTitle("");
      setBody("");
      setMessage({ ok: true, text: `Опубликовано. Уведомлено студентов: ${result.notified}.` });
    } catch (caught) {
      const apiError = caught as ApiError;
      setErrors(apiError.fields ?? {});
      setMessage({ ok: false, text: apiError.fields ? "Проверьте отмеченные поля." : apiError.message });
    }
  }

  const err = (key: string) => errors[key] && <span className="mt-1 block text-[13px] font-normal text-danger">{errors[key]}</span>;

  return (
    <div className="grid gap-4">
      <PageTitle title="Объявления" subtitle="Студенты получат уведомление в кабинете" />
      <Card>
        <form onSubmit={submit} noValidate className="grid gap-3">
          <label className="text-sm font-semibold">
            Кому
            <select className={inputClass} value={audience} onChange={(e) => setAudience(e.target.value)}>
              <option value="">Выберите адресатов</option>
              {user?.role === "admin" && <option value="all">Все студенты</option>}
              {summary.data?.faculties.map((f) => (
                <option key={f.code} value={`faculty:${f.code}`}>
                  {f.name}
                </option>
              ))}
              {groups.data?.map((g) => (
                <option key={g.id} value={`group:${g.id}`}>
                  Группа {g.name}
                </option>
              ))}
            </select>
            {err("audience") || err("faculty") || err("groupId")}
          </label>
          <label className="text-sm font-semibold">
            Заголовок
            <input className={inputClass} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
            {err("title")}
          </label>
          <label className="text-sm font-semibold">
            Текст
            <textarea className={cx(inputClass, "py-3")} rows={4} value={body} maxLength={4000} onChange={(e) => setBody(e.target.value)} />
            {err("body")}
          </label>
          {message && (
            <p role={message.ok ? "status" : "alert"} className={cx("m-0 text-sm font-semibold", message.ok ? "text-ok" : "text-danger")}>
              {message.text}
            </p>
          )}
          <Button type="submit" busy={create.isPending}>
            Опубликовать
          </Button>
        </form>
      </Card>

      {list.isPending ? (
        <Skeleton rows={2} />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : (
        <div className="grid gap-2">
          {list.data.map((item) => (
            <Card key={item.id}>
              <Kicker>
                {item.audience} · {dateTime(item.publishedAt)}
              </Kicker>
              <p className="m-0 mt-1.5 font-semibold leading-snug">{item.title}</p>
              <p className="m-0 mt-1 whitespace-pre-wrap break-words text-sm text-muted">{item.body}</p>
              <p className="m-0 mt-1.5 text-xs text-muted">Автор: {item.author}</p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

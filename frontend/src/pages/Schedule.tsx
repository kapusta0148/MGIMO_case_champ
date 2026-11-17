import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useSchedule } from "../api/hooks";
import type { Deadline, ScheduleDay } from "../api/types";
import { LessonCard } from "../components/LessonCard";
import { Badge, Card, cx, EmptyState, ErrorState, PageTitle, Skeleton } from "../components/ui";
import { addDays, dayMonth, dueText, fullDate, shortDate, time } from "../lib/format";
import { useQuery } from "@tanstack/react-query";

type View = "day" | "week" | "deadlines";

function mondayOf(isoDate: string) {
  const weekday = new Date(`${isoDate}T00:00:00Z`).getUTCDay(); // 0 = вс
  return addDays(isoDate, weekday === 0 ? -6 : 1 - weekday);
}

function DayBlock({ day, highlightId }: { day: ScheduleDay; highlightId: number | null }) {
  const empty = day.lessons.length === 0 && day.movedAway.length === 0;
  return (
    <section aria-label={fullDate(day.date)}>
      <h2 className="m-0 mb-2 flex items-center gap-2 text-sm font-bold first-letter:uppercase">
        {fullDate(day.date)}
        {day.isToday && <Badge tone="accent">сегодня</Badge>}
      </h2>
      {empty ? (
        <p className="m-0 rounded-[18px] border border-dashed border-line p-4 text-[13px] text-muted">Занятий нет.</p>
      ) : (
        <div className="grid gap-2">
          {day.lessons.map((lesson) => (
            <LessonCard key={lesson.id} lesson={lesson} highlight={lesson.id === highlightId} />
          ))}
          {day.movedAway.map((lesson) => (
            <p key={`away-${lesson.id}`} className="m-0 rounded-[18px] border border-dashed border-warn/50 p-3 text-[13px] text-muted">
              <s>
                {time(lesson.change!.originalStartsAt)}–{time(lesson.change!.originalEndsAt)} · {lesson.subject.name}
              </s>{" "}
              — перенесено на {lesson.change!.dateChanged ? `${shortDate(lesson.date)}, ` : ""}
              {time(lesson.startsAt)}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

function Deadlines({ today }: { today: string }) {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["deadlines"],
    queryFn: () => api<{ items: Deadline[] }>("/me/deadlines").then((d) => d.items),
  });
  if (isPending) return <Skeleton />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data.length) return <EmptyState title="Дедлайнов нет" text="Когда появятся новые задания, они будут здесь." />;
  return (
    <div className="grid gap-2">
      {data.map((d) => (
        <Card key={d.id}>
          <div className="flex items-start justify-between gap-2">
            <p className="m-0 font-semibold leading-snug">{d.title}</p>
            <Badge tone={d.isSoon ? "warn" : "neutral"}>{dueText(d.dueAt, today)}</Badge>
          </div>
          <p className="m-0 mt-1 text-sm text-muted">
            {d.kindLabel}
            {d.subject && ` · ${d.subject.name}`}
          </p>
          {d.description && <p className="m-0 mt-1.5 text-sm">{d.description}</p>}
        </Card>
      ))}
    </div>
  );
}

export function SchedulePage() {
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View) || (params.get("date") ? "day" : "week");
  const date = params.get("date");
  const highlightId = params.get("lesson") ? Number(params.get("lesson")) : null;

  // Без даты сервер сам выбирает текущую неделю (в воскресенье — следующую).
  const weekStart = date ? mondayOf(date) : null;
  const { data, error, isPending, refetch } = useSchedule(weekStart, weekStart ? addDays(weekStart, 6) : null);

  const today = data?.today ?? "";
  const selectedDay = date ?? today;

  useEffect(() => {
    if (!highlightId || !data) return;
    document.getElementById(`lesson-${highlightId}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlightId, data]);

  function go(next: Record<string, string | null>) {
    const merged = new URLSearchParams(params);
    merged.delete("lesson");
    for (const [key, value] of Object.entries(next)) value === null ? merged.delete(key) : merged.set(key, value);
    setParams(merged, { replace: true });
  }

  const tabs: { key: View; label: string }[] = [
    { key: "day", label: "День" },
    { key: "week", label: "Неделя" },
    { key: "deadlines", label: "Дедлайны" },
  ];
  const days = data?.days ?? [];
  const visibleDays = view === "day" ? days.filter((d) => d.date === selectedDay) : days;

  return (
    <div>
      <PageTitle title="Расписание" subtitle="Время московское" />

      <div role="tablist" aria-label="Вид расписания" className="mb-3 grid grid-cols-3 gap-1 rounded-[14px] bg-surface-2 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={view === tab.key}
            onClick={() => go({ view: tab.key, date: tab.key === "day" ? selectedDay || null : date })}
            className={cx(
              "min-h-10 rounded-[11px] text-sm font-semibold",
              view === tab.key ? "mc-tab-active" : "text-muted",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {view === "deadlines" ? (
        today ? <Deadlines today={today} /> : <Skeleton />
      ) : isPending ? (
        <Skeleton rows={4} />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <div className="mb-3 flex items-center justify-between gap-2">
            <button
              aria-label="Предыдущая неделя"
              onClick={() => go({ date: addDays(data.from, -7), view })}
              className="grid size-11 place-items-center rounded-[13px] border border-line bg-surface text-text"
            >
              <ChevronLeft size={18} aria-hidden />
            </button>
            <button onClick={() => go({ date: null, view: "week" })} className="min-h-11 px-2 text-sm font-semibold text-text">
              {dayMonth(data.from)} — {dayMonth(data.to)}
            </button>
            <button
              aria-label="Следующая неделя"
              onClick={() => go({ date: addDays(data.from, 7), view })}
              className="grid size-11 place-items-center rounded-[13px] border border-line bg-surface text-text"
            >
              <ChevronRight size={18} aria-hidden />
            </button>
          </div>

          {view === "day" && (
            <div className="mb-3 grid grid-cols-7 gap-1" role="group" aria-label="День недели">
              {days.map((day) => (
                <button
                  key={day.date}
                  onClick={() => go({ date: day.date, view: "day" })}
                  aria-pressed={day.date === selectedDay}
                  className={cx(
                    "relative min-h-12 rounded-xl border text-xs font-semibold",
                    day.date === selectedDay ? "mc-grad border-transparent" : "border-line bg-surface text-text",
                  )}
                >
                  <span className="block opacity-80">{day.weekdayShort}</span>
                  {Number(day.date.slice(8))}
                  {day.lessons.some((l) => l.change) && (
                    <span className="absolute right-1 top-1 size-1.5 rounded-full bg-warn" aria-label="есть изменения" />
                  )}
                </button>
              ))}
            </div>
          )}

          {data.changes.length > 0 && view === "week" && (
            <p className="m-0 mb-3 rounded-[14px] bg-warn-soft p-3 text-[13px] text-warn">
              На этой неделе изменений в расписании: {data.changes.length}. Они отмечены в списке.
            </p>
          )}

          <div className="grid gap-5">
            {visibleDays.map((day) => (
              <DayBlock key={day.date} day={day} highlightId={highlightId} />
            ))}
            {visibleDays.length === 0 && <EmptyState title="Этот день вне выбранной недели" />}
          </div>
        </>
      )}
    </div>
  );
}

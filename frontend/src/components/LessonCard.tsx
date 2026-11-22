import { ArrowLeftRight, MapPin } from "lucide-react";
import type { Lesson } from "../api/types";
import { shortDate, time, timeRange } from "../lib/format";
import { Badge, cx } from "./ui";

const CHANGE_LABEL = { moved: "Перенос", room: "Другая аудитория", cancelled: "Отменено" } as const;

/** Старое → новое значение занятия. Одинаково выглядит в расписании, уведомлении и на «Сегодня». */
export function ChangeLine({ lesson }: { lesson: Lesson }) {
  const change = lesson.change;
  if (!change || change.type === "cancelled") return null;
  return (
    <span className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
      <span className="sr-only">Было: </span>
      <s className="text-muted decoration-1">
        {change.dateChanged && `${shortDate(change.originalDate)}, `}
        {time(change.originalStartsAt)} · ауд. {change.originalRoom}
      </s>
      <span aria-hidden className="text-muted">
        →
      </span>
      <span className="sr-only">Стало: </span>
      <strong className="font-semibold text-warn">
        {change.dateChanged && `${shortDate(lesson.date)}, `}
        {time(lesson.startsAt)} · ауд. {lesson.room}
      </strong>
    </span>
  );
}

/** Одно занятие в списке расписания и в уведомлении о переносе. */
export function LessonCard({ lesson, highlight, showDate }: { lesson: Lesson; highlight?: boolean; showDate?: boolean }) {
  const change = lesson.change;
  const cancelled = lesson.status === "cancelled";
  return (
    <article
      id={`lesson-${lesson.id}`}
      className={cx(
        "mc-rise scroll-mt-24 rounded-[20px] border bg-surface p-4",
        change ? "border-warn/50" : "border-line",
        highlight && "ring-2 ring-accent-2 ring-offset-2 ring-offset-bg",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className={cx("min-w-0", cancelled && "opacity-60")}>
          {showDate && <div className="text-xs font-medium text-muted">{shortDate(lesson.date)}</div>}
          <div className={cx("font-display text-[17px] font-semibold tabular-nums leading-tight", cancelled && "line-through")}>
            {timeRange(lesson.startsAt, lesson.endsAt)}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {lesson.pairNumber && !change && <Badge>{lesson.pairNumber} пара</Badge>}
          {change && (
            <Badge tone={cancelled ? "danger" : "warn"}>
              <ArrowLeftRight size={12} aria-hidden /> {CHANGE_LABEL[change.type]}
            </Badge>
          )}
        </div>
      </div>

      <h3 className="m-0 mt-2 text-[15px] font-semibold leading-snug">{lesson.subject.name}</h3>
      <p className="m-0 mt-0.5 text-[13px] text-muted">
        {lesson.kindLabel} · {lesson.teacher.title} {lesson.teacher.shortName}
      </p>
      {!cancelled && (
        <p className="m-0 mt-2 flex items-center gap-1.5 text-sm font-semibold">
          <MapPin size={15} className="shrink-0 text-accent-2" aria-hidden /> ауд. {lesson.room}
        </p>
      )}

      {change && (
        <div className="mt-3 rounded-2xl bg-warn-soft p-3 text-[13px] leading-relaxed">
          <ChangeLine lesson={lesson} />
          {cancelled && <strong className="text-danger">Занятие отменено.</strong>}
          {change.reason && <p className="m-0 mt-1 text-muted">Причина: {change.reason}</p>}
        </div>
      )}
    </article>
  );
}

import { ArrowLeftRight, ArrowRight, Bell, Hourglass, Timer } from "lucide-react";
import { Link } from "react-router-dom";
import { useDashboard } from "../api/hooks";
import type { Dashboard, Lesson } from "../api/types";
import { ChangeLine } from "../components/LessonCard";
import { Badge, Card, CardLink, cx, ErrorState, Kicker, Skeleton, STATUS_TONE } from "../components/ui";
import { dueText, fullDate, plural, shortDate, time, timeRange, untilText } from "../lib/format";

const lessonLink = (lesson: Lesson) => `/schedule?date=${lesson.date}&lesson=${lesson.id}`;

function summaryLine(d: Dashboard) {
  const s = d.summary;
  const parts = [
    s.lessonsToday ? `${s.lessonsToday} ${plural(s.lessonsToday, "пара", "пары", "пар")}` : "занятий нет",
  ];
  if (s.changesToday) parts.push(`${s.changesToday} ${plural(s.changesToday, "перенос", "переноса", "переносов")}`);
  if (s.deadlinesSoon) parts.push(`${s.deadlinesSoon} ${plural(s.deadlinesSoon, "дедлайн", "дедлайна", "дедлайнов")}`);
  return `Сегодня ${parts.join(" · ")}`;
}

/** Следующая пара в виде посадочного талона: время «вылета» и «прилёта», аудитория как гейт. */
function BoardingPass({ lesson }: { lesson: Lesson }) {
  const changed = lesson.change && lesson.change.type !== "cancelled";
  return (
    <Link
      to={lessonLink(lesson)}
      className="mc-pass mc-rise block text-text no-underline"
      aria-label={`Следующая пара: ${lesson.subject.name}, ${timeRange(lesson.startsAt, lesson.endsAt)}, аудитория ${lesson.room}. Открыть в расписании`}
    >
      <div className="px-4 pb-3.5 pt-3.5">
        <div className="flex items-center justify-between gap-2">
          <Kicker>Следующая пара</Kicker>
          <Badge tone="cyan">
            <Timer size={12} aria-hidden />
            {untilText(lesson.minutesUntil ?? 0, lesson.startsAt, Boolean(lesson.isToday))}
          </Badge>
        </div>
        <div className="my-3 flex items-center gap-2.5" aria-hidden>
          <b className="font-display text-[26px] font-bold leading-none tracking-tight tabular-nums">{time(lesson.startsAt)}</b>
          <span className="mc-route">
            <span className="mc-route-dot mc-ping" style={{ left: "12%" }} />
          </span>
          <b className="font-display text-[26px] font-bold leading-none tracking-tight tabular-nums">{time(lesson.endsAt)}</b>
        </div>
        <p className="m-0 text-base font-semibold leading-snug">{lesson.subject.name}</p>
        <p className="m-0 mt-0.5 text-[13px] text-muted">
          {lesson.kindLabel} · {lesson.teacher.title} {lesson.teacher.shortName}
        </p>
        {changed && (
          <p className="m-0 mt-2 text-[13px]">
            <ChangeLine lesson={lesson} />
          </p>
        )}
      </div>
      <div className="mc-perf" />
      <div className="grid grid-cols-3 gap-2 px-4 pb-3.5 pt-3">
        <div>
          <Kicker className="text-[9.5px]">Аудитория</Kicker>
          <b className={cx("font-display text-[15px] font-semibold", changed && lesson.change?.roomChanged && "text-warn")}>
            {lesson.room}
          </b>
        </div>
        <div>
          <Kicker className="text-[9.5px]">Пара</Kicker>
          <b className="font-display text-[15px] font-semibold">{lesson.pairNumber ? `№ ${lesson.pairNumber}` : "—"}</b>
        </div>
        <div>
          <Kicker className="text-[9.5px]">День</Kicker>
          <b className="font-display text-[15px] font-semibold">{lesson.isToday ? "сегодня" : shortDate(lesson.date).split(",")[0]}</b>
        </div>
      </div>
    </Link>
  );
}

function ChangeRow({ lesson, today }: { lesson: Lesson; today: string }) {
  const cancelled = lesson.status === "cancelled";
  const title = cancelled ? "отменено" : lesson.change?.timeChanged ? "перенесено" : "в другой аудитории";
  return (
    <Link
      to={lessonLink(lesson)}
      className="mc-rise mc-rise-2 flex items-center gap-3 rounded-[18px] border border-warn/45 bg-surface p-3 text-text no-underline"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-[11px] bg-warn-soft text-warn">
        <ArrowLeftRight size={17} aria-hidden />
      </span>
      <span className="min-w-0 flex-1 text-[13px] text-muted">
        <b className="block text-sm font-semibold text-text">
          {lesson.subject.name}: {title}
        </b>
        {lesson.date !== today && !lesson.change?.dateChanged && (
          <span className="mr-1.5 font-semibold text-text">{shortDate(lesson.date)}:</span>
        )}
        {cancelled ? (
          <s>
            {lesson.date !== today && `${shortDate(lesson.date)}, `}
            {timeRange(lesson.startsAt, lesson.endsAt)}
          </s>
        ) : (
          <ChangeLine lesson={lesson} />
        )}
      </span>
    </Link>
  );
}

/** Объяснимая подсказка: ближайшее свободное окно между оставшимися сегодня парами (правило, не ИИ). */
function freeWindow(d: Dashboard): { from: string; to: string; minutes: number } | null {
  const now = d.now;
  const lessons = d.todayLessons.filter((l) => l.status !== "cancelled").sort((a, b) => a.startsAt.localeCompare(b.startsAt));
  for (let i = 0; i < lessons.length - 1; i++) {
    const from = lessons[i].endsAt > now ? lessons[i].endsAt : now;
    const to = lessons[i + 1].startsAt;
    const minutes = Math.round((Date.parse(to) - Date.parse(from)) / 60000);
    if (to > now && minutes >= 60) return { from, to, minutes };
  }
  return null;
}

export function TodayPage() {
  const { data, error, isPending, refetch } = useDashboard();
  if (isPending) return <Skeleton rows={4} />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const { nextLesson, currentLesson, changes, deadlines, activeRequest } = data;
  const nearest = deadlines[0];
  const window = freeWindow(data);

  return (
    <div>
      <header className="mb-4">
        <p className="m-0 text-[13px] text-muted first-letter:uppercase">{fullDate(data.today)}</p>
        <h1 className="m-0 mt-1 font-display text-[23px] font-bold leading-tight tracking-tight">Привет, {data.firstName}</h1>
        <p className="m-0 mt-1 text-[13px] text-muted">{summaryLine(data)}</p>
      </header>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] lg:items-start lg:gap-5">
        {/* Левая колонка: 1) идущая и следующая пара, 2) изменения */}
        <div className="grid gap-3">
          {currentLesson && (
            <Card className="py-3">
              <div className="flex items-center justify-between gap-2">
                <Kicker>Идёт сейчас</Kicker>
                <Badge tone="ok">ещё {currentLesson.minutesLeft} мин</Badge>
              </div>
              <p className="m-0 mt-1 text-sm font-semibold">{currentLesson.subject.name}</p>
              <p className="m-0 text-[13px] text-muted">
                {timeRange(currentLesson.startsAt, currentLesson.endsAt)} · ауд. {currentLesson.room}
              </p>
            </Card>
          )}

          {nextLesson ? (
            <BoardingPass lesson={nextLesson} />
          ) : (
            <Card>
              <Kicker>Следующая пара</Kicker>
              <p className="m-0 mt-1.5 text-sm text-muted">В расписании пока нет предстоящих занятий.</p>
            </Card>
          )}

          {changes.length > 0 && (
            <section aria-label="Изменения в расписании" className="grid gap-2">
              {changes.map((lesson) => (
                <ChangeRow key={lesson.id} lesson={lesson} today={data.today} />
              ))}
            </section>
          )}
        </div>

        {/* Правая колонка: 3) дедлайн, 4) заявка, 5) подсказка и непрочитанное */}
        <div className="grid gap-3">
          <div className="grid grid-cols-2 gap-3">
            <CardLink to="/schedule?view=deadlines" className="mc-rise-3 p-3.5">
              <Kicker>Дедлайн</Kicker>
              {nearest ? (
                <>
                  <b className="mt-1.5 line-clamp-3 block text-[13.5px] font-semibold leading-snug">{nearest.title}</b>
                  <span className={cx("mt-1.5 block text-xs font-semibold", nearest.isSoon ? "text-warn" : "text-muted")}>
                    {dueText(nearest.dueAt, data.today)}
                  </span>
                </>
              ) : (
                <span className="mt-1.5 block text-[13px] text-muted">Ближайших нет</span>
              )}
            </CardLink>

            {activeRequest ? (
              <CardLink to={`/requests/${activeRequest.id}`} className="mc-rise-3 p-3.5">
                <Kicker>Заявка</Kicker>
                <b className="mt-1.5 line-clamp-3 block text-[13.5px] font-semibold leading-snug">{activeRequest.title}</b>
                <span className="mt-1.5 block">
                  <Badge tone={STATUS_TONE[activeRequest.status]}>{activeRequest.statusLabel.toLowerCase()}</Badge>
                </span>
              </CardLink>
            ) : (
              <CardLink to="/requests/new" className="mc-rise-3 p-3.5">
                <Kicker>Заявка</Kicker>
                <b className="mt-1.5 flex items-center gap-1 text-[13.5px] font-semibold leading-snug">
                  Заказать справку <ArrowRight size={15} aria-hidden />
                </b>
              </CardLink>
            )}
          </div>

          <Link
            to="/planner"
            className="mc-rise mc-rise-4 flex items-center gap-3 rounded-[18px] border border-line bg-surface-2 p-3.5 text-[13px] text-text no-underline hover:border-accent-2/50"
          >
            <Hourglass size={18} className="shrink-0 text-accent-2" aria-hidden />
            <p className="m-0 flex-1 text-muted">
              {window ? (
                <>
                  <b className="text-text">
                    Окно {time(window.from)}–{time(window.to)}.
                  </b>{" "}
                  {Math.floor(window.minutes / 60) > 0 && `${Math.floor(window.minutes / 60)} ч `}
                  {window.minutes % 60 > 0 && `${window.minutes % 60} мин `}
                  между парами
                  {nearest?.isSoon ? ` — можно заняться «${nearest.title.replace(/[«»]/g, "")}».` : "."}
                </>
              ) : (
                <>
                  <b className="text-text">План на неделю:</b> свободные окна и подготовка к дедлайнам.
                </>
              )}
            </p>
            <ArrowRight size={16} className="shrink-0 text-muted" aria-hidden />
          </Link>

          {data.notifications.length > 0 && (
            <CardLink to="/notifications" className="mc-rise-4">
              <div className="flex items-center justify-between gap-2">
                <Kicker className="flex items-center gap-1.5">
                  <Bell size={12} aria-hidden /> Новое
                </Kicker>
                <Badge tone="warn">{data.summary.unreadNotifications}</Badge>
              </div>
              <ul className="m-0 mt-2 grid list-none gap-1.5 p-0 text-[13px]">
                {data.notifications.map((n) => (
                  <li key={n.id} className="truncate">
                    <span className="text-muted">{n.kindLabel}:</span> {n.title}
                  </li>
                ))}
              </ul>
            </CardLink>
          )}

          {activeRequest && (
            <Link
              to="/requests/new"
              className="flex min-h-11 items-center justify-center gap-1.5 rounded-[14px] border border-dashed border-line text-[13px] font-semibold text-muted no-underline hover:text-text"
            >
              Заказать справку или подать заявление <ArrowRight size={15} aria-hidden />
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

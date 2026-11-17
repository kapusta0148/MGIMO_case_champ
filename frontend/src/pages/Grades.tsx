import { ChevronDown } from "lucide-react";
import { useGrades } from "../api/hooks";
import type { CourseGrades, TermGrades } from "../api/types";
import { Badge, Card, ErrorState, Kicker, PageTitle, Skeleton } from "../components/ui";
import { dateTime, dayMonth } from "../lib/format";

const SESSION_STATE = { upcoming: "впереди", in_progress: "идёт", closed: "закрыта" } as const;

/** Сегодняшняя дата по Москве (ГГГГ-ММ-ДД): работа с прошедшей датой без балла — «на проверке», а не «ожидается». */
const moscowToday = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Moscow" }).format(new Date());

function FinalBadge({ course }: { course: CourseGrades }) {
  const result = course.final.result;
  if (!result) return <Badge>ожидается</Badge>;
  const text = result.type === "credit" ? result.label : `${result.mark} · ${result.label}`;
  return <Badge tone={result.passed ? "ok" : "danger"}>{text}</Badge>;
}

function CurrentCourse({ course }: { course: CourseGrades }) {
  return (
    <details className="mc-rise group rounded-[20px] border border-line bg-surface">
      <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <p className="m-0 font-semibold leading-snug">{course.subject.name}</p>
          <p className="m-0 mt-0.5 text-sm text-muted">
            {course.controlFormLabel} · {course.teacher.shortName}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-display text-xl font-semibold tabular-nums leading-none">
            {course.currentScore ?? "—"}
            {course.currentLetter && <span className="ml-1 text-sm font-semibold text-muted">{course.currentLetter}</span>}
          </div>
          {course.atRisk && <span className="text-xs font-semibold text-warn">зона внимания</span>}
        </div>
        <ChevronDown size={18} className="shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="border-t border-line px-4 pb-4 pt-3">
        <Kicker>Текущий контроль</Kicker>
        <ul className="m-0 mt-2 grid list-none gap-2 p-0 text-sm">
          {course.controls.map((control) => (
            <li key={control.id} className="flex items-center justify-between gap-3">
              <span className="min-w-0">
                {control.title}
                {control.date && <span className="text-muted"> · {dayMonth(control.date)}</span>}
              </span>
              {control.status === "graded" ? (
                <strong className="shrink-0 tabular-nums">{control.score} из 100</strong>
              ) : control.date && control.date <= moscowToday() ? (
                <Badge tone="cyan">на проверке</Badge>
              ) : (
                <Badge>ожидается</Badge>
              )}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex items-center justify-between gap-3 rounded-[14px] bg-surface-2 p-3 text-sm">
          <span>
            <strong>{course.controlFormLabel}</strong>
            {course.final.startsAt && (
              <span className="text-muted">
                {" "}
                · {dateTime(course.final.startsAt)}, ауд. {course.final.room}
              </span>
            )}
          </span>
          <FinalBadge course={course} />
        </div>
      </div>
    </details>
  );
}

function PastTerm({ term }: { term: TermGrades }) {
  const { debts, retaken, averageFinalScore } = term.summary;
  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <h2 className="m-0 font-display text-[15px] font-semibold">{term.title}</h2>
        <Badge tone={debts.length ? "danger" : "ok"}>{debts.length ? `долгов: ${debts.length}` : "без долгов"}</Badge>
      </div>
      <p className="m-0 mt-1 text-sm text-muted">
        {term.session.title} {SESSION_STATE[term.session.state]}
        {averageFinalScore !== null && ` · средний балл ${averageFinalScore}`}
        {retaken.length > 0 && ` · пересдачи: ${retaken.join(", ")}`}
      </p>
      <ul className="m-0 mt-3 grid list-none gap-2.5 p-0 text-sm">
        {term.courses.map((course) => (
          <li key={course.courseId} className="flex items-center justify-between gap-3">
            <span className="min-w-0">
              {course.subject.name}
              <span className="text-muted">
                {" "}
                · {course.controlFormLabel.toLowerCase()}
                {course.final.retakes > 0 && ", со 2-й попытки"}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              {course.final.result && <span className="tabular-nums text-muted">{course.final.result.score}</span>}
              <FinalBadge course={course} />
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function GradesPage() {
  const { data, error, isPending, refetch } = useGrades();
  if (isPending) return <Skeleton rows={5} />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;
  const term = data.currentTerm;

  return (
    <div className="grid gap-3">
      <PageTitle title="Успеваемость" subtitle={term?.title} />

      {term && (
        <>
          <Card>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <div className="font-display text-2xl font-semibold tabular-nums">{term.summary.averageCurrentScore ?? "—"}</div>
                <div className="text-xs text-muted">средний балл семестра</div>
              </div>
              <div>
                <div className="font-display text-2xl font-semibold tabular-nums">{term.summary.coursesTotal}</div>
                <div className="text-xs text-muted">дисциплин</div>
              </div>
              <div>
                <div className={`font-display text-2xl font-semibold tabular-nums ${term.summary.atRisk.length ? "text-warn" : ""}`}>
                  {term.summary.atRisk.length}
                </div>
                <div className="text-xs text-muted">в зоне внимания</div>
              </div>
            </div>
            <p className="m-0 mt-3 text-sm">
              <strong>{term.session.title}</strong> {SESSION_STATE[term.session.state]}: {dayMonth(term.session.startsOn)} —{" "}
              {dayMonth(term.session.endsOn)}. Сдано {term.summary.finalsDone} из {term.summary.coursesTotal}.
            </p>
            {term.summary.atRisk.length > 0 && (
              <p className="m-0 mt-2 rounded-[14px] bg-warn-soft p-3 text-[13px] text-warn">
                Обратите внимание: {term.summary.atRisk.join(", ")}. {data.explanations.atRisk}
              </p>
            )}
          </Card>

          <div className="grid gap-2">
            {term.courses.map((course) => (
              <CurrentCourse key={course.courseId} course={course} />
            ))}
          </div>
          <p className="m-0 px-1 text-xs text-muted">
            {data.explanations.currentScore} {data.explanations.expected}
          </p>
        </>
      )}

      {data.pastTerms.map((past) => (
        <PastTerm key={past.id} term={past} />
      ))}

      <Card>
        <Kicker>Шкала прототипа</Kicker>
        <div className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          {data.scale.map((row) => (
            <div key={row.letter} className="flex justify-between gap-2">
              <span>
                <strong>{row.letter}</strong> · {row.min}–{row.max}
              </span>
              <span className="text-muted">{row.label}</span>
            </div>
          ))}
        </div>
        <p className="m-0 mt-2 text-xs text-muted">Зачёт — от {data.passThreshold} баллов. Шкала демонстрационная.</p>
      </Card>
    </div>
  );
}

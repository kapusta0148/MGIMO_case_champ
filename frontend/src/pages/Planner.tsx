import { CalendarPlus, Check, Info, Trash2, TriangleAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { useCreateTask, useDeleteTask, usePlanner, useTasks, useToggleTask } from "../api/hooks";
import type { PersonalTask, PlannerBlock } from "../api/types";
import { Badge, Button, Card, cx, EmptyState, ErrorState, Kicker, PageTitle, Skeleton } from "../components/ui";
import { dateTime, shortDate, time, timeRange } from "../lib/format";

const inputClass =
  "mt-1.5 block min-h-11 w-full rounded-[14px] border border-line bg-surface px-3.5 text-base text-text outline-none transition-colors focus:border-accent-2";

const hours = (minutes: number) => {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h && m ? `${h} ч ${m} мин` : h ? `${h} ч` : `${m} мин`;
};

/** Коротко для узкой колонки: «3:45». */
const short = (minutes: number) => `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;

// ── Нагрузка по дням ──────────────────────────────────────────────────────────

function WeekLoad({ days }: { days: NonNullable<ReturnType<typeof usePlanner>["data"]>["days"] }) {
  const scale = 720; // 12 часов учебного дня
  return (
    <Card>
      <Kicker>Неделя</Kicker>
      <ul className="m-0 mt-2.5 grid list-none gap-2 p-0">
        {days.map((day) => {
          const parts = [
            { value: day.lessonsMinutes, className: "bg-accent", label: "пары" },
            { value: day.plannedMinutes, className: "bg-ok", label: "мои задачи" },
            { value: day.suggestedMinutes, className: "bg-accent-2/70", label: "предложено" },
          ];
          return (
            <li key={day.date} className="grid grid-cols-[2rem_minmax(0,1fr)_5.6rem] items-center gap-2 text-xs">
              <span className="font-semibold uppercase text-muted">{day.weekdayShort}</span>
              <span className="flex h-2.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
                {parts.map((part) => (
                  <span key={part.label} className={part.className} style={{ width: `${Math.min(100, (part.value / scale) * 100)}%` }} />
                ))}
              </span>
              <span className="whitespace-nowrap text-right tabular-nums text-muted">
                <span className="sr-only">
                  {shortDate(day.date)}: пары {hours(day.lessonsMinutes)}, свободно {hours(day.freeMinutes)}.
                </span>
                <span aria-hidden>своб. {short(day.freeMinutes)}</span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="m-0 mt-2.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted" aria-hidden>
        <span className="inline-flex items-center gap-1">
          <i className="size-2 rounded-full bg-accent" /> пары
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="size-2 rounded-full bg-ok" /> мои задачи
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="size-2 rounded-full bg-accent-2/70" /> предложено
        </span>
      </p>
    </Card>
  );
}

// ── Мои задачи ────────────────────────────────────────────────────────────────

function TaskRow({ task }: { task: PersonalTask }) {
  const toggle = useToggleTask();
  const remove = useDeleteTask();
  const when = task.plannedStart
    ? `${shortDate(task.plannedStart)}, ${timeRange(task.plannedStart, task.plannedEnd!)}`
    : task.dueAt
      ? `до ${dateTime(task.dueAt)}`
      : null;
  return (
    <li className="flex items-center gap-3 rounded-[16px] border border-line bg-surface p-3">
      <button
        role="checkbox"
        aria-checked={task.completed}
        aria-label={`Выполнено: ${task.title}`}
        disabled={toggle.isPending}
        onClick={() => toggle.mutate({ id: task.id, completed: !task.completed })}
        className={cx(
          "grid size-11 shrink-0 place-items-center rounded-[12px] border",
          task.completed ? "mc-grad border-transparent" : "border-line bg-surface-2 text-transparent",
        )}
      >
        <Check size={18} aria-hidden />
      </button>
      <div className="min-w-0 flex-1">
        <p className={cx("m-0 text-sm font-semibold leading-snug", task.completed && "text-muted line-through")}>{task.title}</p>
        <p className="m-0 mt-0.5 text-xs text-muted">
          {when}
          {task.fromPlanner && (when ? " · " : "") + "из плана"}
          {task.estimatedMinutes && !task.plannedStart ? ` · ${hours(task.estimatedMinutes)}` : ""}
        </p>
      </div>
      <button
        aria-label={`Удалить: ${task.title}`}
        disabled={remove.isPending}
        onClick={() => remove.mutate(task.id)}
        className="grid size-11 shrink-0 place-items-center rounded-[12px] text-muted hover:text-danger"
      >
        <Trash2 size={17} aria-hidden />
      </button>
    </li>
  );
}

function AddTask() {
  const create = useCreateTask();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [estimate, setEstimate] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function submit(event: FormEvent) {
    event.preventDefault();
    setErrors({});
    if (title.trim().length < 2) return setErrors({ title: "Опишите задачу (от 2 символов)." });
    try {
      await create.mutateAsync({
        title,
        dueAt: due || null,
        estimatedMinutes: estimate ? Number(estimate) : null,
      });
      setTitle("");
      setDue("");
      setEstimate("");
    } catch (caught) {
      const apiError = caught as ApiError;
      setErrors(apiError.fields ?? { title: apiError.message });
    }
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-3 rounded-[18px] border border-dashed border-line p-3.5">
      <label className="text-sm font-semibold">
        Новая задача
        <input
          className={inputClass}
          value={title}
          maxLength={160}
          placeholder="Например: прочитать главу 4"
          onChange={(e) => setTitle(e.target.value)}
        />
        {errors.title && <span className="mt-1 block text-[13px] font-normal text-danger">{errors.title}</span>}
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm font-semibold">
          Срок
          <input type="datetime-local" className={inputClass} value={due} onChange={(e) => setDue(e.target.value)} />
          {errors.dueAt && <span className="mt-1 block text-[13px] font-normal text-danger">{errors.dueAt}</span>}
        </label>
        <label className="text-sm font-semibold">
          Сколько времени
          <select className={inputClass} value={estimate} onChange={(e) => setEstimate(e.target.value)}>
            <option value="">Не знаю</option>
            {[30, 60, 90, 120, 180, 240].map((m) => (
              <option key={m} value={m}>
                {hours(m)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="m-0 text-xs text-muted">Задачу со сроком и временем планировщик тоже разложит по свободным окнам.</p>
      <Button type="submit" variant="ghost" busy={create.isPending}>
        Добавить задачу
      </Button>
    </form>
  );
}

// ── Предложения ───────────────────────────────────────────────────────────────

function BlockCard({ block }: { block: PlannerBlock }) {
  const create = useCreateTask();
  const [error, setError] = useState<string | null>(null);
  return (
    <article className="mc-rise rounded-[20px] border border-accent-2/40 bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="font-display text-[16px] font-semibold tabular-nums">{timeRange(block.startsAt, block.endsAt)}</div>
        <Badge tone={block.atRisk ? "warn" : "cyan"}>{hours(block.minutes)}</Badge>
      </div>
      <p className="m-0 mt-1.5 text-[15px] font-semibold leading-snug">{block.title}</p>
      <p className="m-0 mt-0.5 text-[13px] text-muted">
        {block.kindLabel}
        {block.subject && ` · ${block.subject}`} · срок {dateTime(block.dueAt)}
      </p>
      <details className="mt-2 text-[13px]">
        <summary className="min-h-9 cursor-pointer py-1.5 font-semibold text-accent-text">Почему так?</summary>
        <ul className="m-0 mt-1 grid gap-1 pl-4 text-muted">
          {block.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </details>
      {error && (
        <p role="alert" className="m-0 mt-1 text-sm text-danger">
          {error}
        </p>
      )}
      <Button
        className="mt-2.5 w-full"
        busy={create.isPending}
        onClick={() =>
          create.mutate(
            {
              title: block.title,
              plannedStart: block.startsAt,
              plannedEnd: block.endsAt,
              deadlineId: block.deadlineId,
              sourceKey: block.key,
            },
            { onError: (e) => setError((e as ApiError).message) },
          )
        }
      >
        <CalendarPlus size={16} aria-hidden /> Добавить в мои задачи
      </Button>
    </article>
  );
}

export function PlannerPage() {
  const plan = usePlanner();
  const tasks = useTasks();
  if (plan.isPending || tasks.isPending) return <Skeleton rows={4} />;
  if (plan.error || !plan.data) return <ErrorState error={plan.error} onRetry={() => void plan.refetch()} />;
  if (tasks.error || !tasks.data) return <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />;

  const { blocks, warnings, days, rules } = plan.data;
  const open = tasks.data.filter((t) => !t.completed);
  const done = tasks.data.filter((t) => t.completed);
  const byDay = blocks.reduce<Record<string, PlannerBlock[]>>((acc, block) => {
    (acc[block.date] ??= []).push(block);
    return acc;
  }, {});

  return (
    <div className="grid gap-4">
      <PageTitle title="План на неделю" subtitle="Свободные окна между парами и подготовка к дедлайнам" />

      <p className="m-0 flex gap-2 rounded-[14px] bg-surface-2 p-3 text-[13px] text-muted">
        <Info size={16} className="mt-0.5 shrink-0 text-accent-2" aria-hidden />
        <span>
          Предложения строит <b className="text-text">алгоритм по правилам</b> — по вашему расписанию, дедлайнам и оценкам. В
          ваши задачи ничего не попадает без нажатия «Добавить».
        </span>
      </p>

      {warnings.map((w) => (
        <p key={w.text} role="note" className="m-0 flex gap-2 rounded-[14px] border border-warn/40 bg-warn-soft p-3 text-[13px] text-warn">
          <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden /> {w.text}
        </p>
      ))}

      <WeekLoad days={days} />

      <section aria-labelledby="my-tasks" className="grid gap-2">
        <h2 id="my-tasks" className="m-0 font-display text-[17px] font-semibold">
          Мои задачи {open.length > 0 && <span className="text-muted">· {open.length}</span>}
        </h2>
        {open.length === 0 && done.length === 0 && (
          <p className="m-0 text-sm text-muted">Пока пусто. Добавьте своё дело или примите предложение ниже.</p>
        )}
        <ul className="m-0 grid list-none gap-2 p-0">
          {[...open, ...done.slice(0, 5)].map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </ul>
        <AddTask />
      </section>

      <section aria-labelledby="suggestions" className="grid gap-3">
        <h2 id="suggestions" className="m-0 font-display text-[17px] font-semibold">
          Предложения {blocks.length > 0 && <span className="text-muted">· {blocks.length}</span>}
        </h2>
        {blocks.length === 0 ? (
          <EmptyState title="Всё распределено" text="Новых предложений нет: дедлайны покрыты или свободных окон не осталось." />
        ) : (
          Object.entries(byDay).map(([date, items]) => (
            <div key={date} className="grid gap-2">
              <h3 className="m-0 text-sm font-bold first-letter:uppercase">
                {date === plan.data.today ? "Сегодня" : shortDate(date)}
                <span className="ml-2 font-normal text-muted">с {time(items[0].startsAt)}</span>
              </h3>
              {items.map((block) => (
                <BlockCard key={block.key} block={block} />
              ))}
            </div>
          ))
        )}
      </section>

      <details className="rounded-[18px] border border-line bg-surface p-4 text-[13px]">
        <summary className="cursor-pointer font-semibold">Как работает планировщик</summary>
        <ul className="m-0 mt-2 grid gap-1.5 pl-4 text-muted">
          {rules.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

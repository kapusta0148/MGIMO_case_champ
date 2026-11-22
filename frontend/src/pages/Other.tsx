import { ArrowLeft, LogOut, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAnnouncement, useMarkAllRead, useMarkRead, useNotifications } from "../api/hooks";
import type { Notification, NotificationLink } from "../api/types";
import { homePath, useAuth } from "../auth/AuthContext";
import { PrototypeNote } from "../components/Layout";
import { LessonCard } from "../components/LessonCard";
import { Badge, Button, Card, cx, EmptyState, ErrorState, Kicker, PageTitle, Skeleton } from "../components/ui";
import { dateTime } from "../lib/format";
import { applyTheme, readTheme, type Theme } from "../lib/theme";

// ── Уведомления ───────────────────────────────────────────────────────────────

function linkPath(link: NotificationLink): string {
  switch (link.type) {
    case "lesson":
      return `/schedule?date=${link.date}&lesson=${link.id}`;
    case "request":
      return `/requests/${link.id}`;
    case "announcement":
      return `/announcements/${link.id}`;
    case "deadline":
      return "/schedule?view=deadlines";
    case "grades":
      return "/grades";
  }
}

const LINK_LABEL: Record<NotificationLink["type"], string> = {
  lesson: "Открыть занятие в расписании",
  request: "Открыть заявку",
  announcement: "Читать объявление",
  deadline: "Все дедлайны",
  grades: "Открыть оценки",
};

function NotificationItem({ item }: { item: Notification }) {
  const navigate = useNavigate();
  const markRead = useMarkRead();

  function open() {
    if (!item.read) markRead.mutate(item.id);
    if (item.link) navigate(linkPath(item.link));
  }

  return (
    <article
      className={cx("mc-rise rounded-[20px] border bg-surface p-4", item.read ? "border-line" : "border-accent/60")}
    >
      <div className="flex items-center justify-between gap-2">
        <Badge tone={item.kind === "lesson_change" ? "warn" : "neutral"}>{item.kindLabel}</Badge>
        <span className="flex items-center gap-2 text-xs text-muted">
          {dateTime(item.createdAt)}
          {!item.read && <span className="size-2 rounded-full bg-warn" aria-label="не прочитано" />}
        </span>
      </div>
      <h2 className="m-0 mt-2 text-base font-semibold leading-snug">{item.title}</h2>
      {item.lesson ? (
        <div className="mt-2">
          <LessonCard lesson={item.lesson} showDate />
        </div>
      ) : (
        item.body && <p className="m-0 mt-1 break-words text-sm text-muted">{item.body}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {item.link && (
          <Button onClick={open} className="flex-1">
            {LINK_LABEL[item.link.type]}
          </Button>
        )}
        {!item.read && !item.link && (
          <Button variant="ghost" onClick={() => markRead.mutate(item.id)}>
            Прочитано
          </Button>
        )}
      </div>
    </article>
  );
}

export function NotificationsPage() {
  const { data, error, isPending, refetch } = useNotifications();
  const markAll = useMarkAllRead();
  const action =
    data && data.unreadCount > 0 ? (
      <Button variant="ghost" busy={markAll.isPending} onClick={() => markAll.mutate()} className="shrink-0">
        Прочитать все
      </Button>
    ) : undefined;

  return (
    <div>
      <PageTitle
        title="Уведомления"
        subtitle={data ? (data.unreadCount ? `Непрочитанных: ${data.unreadCount}` : "Всё прочитано") : undefined}
        action={action}
      />
      {isPending ? (
        <Skeleton />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.items.length === 0 ? (
        <EmptyState title="Уведомлений пока нет" text="Здесь появятся переносы занятий, ответы деканата и напоминания." />
      ) : (
        <div className="grid gap-2">
          {data.items.map((item) => (
            <NotificationItem key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

export function AnnouncementPage() {
  const id = Number(useParams().id);
  const { data, error, isPending, refetch } = useAnnouncement(id);
  return (
    <div>
      <Link to="/notifications" className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent-text no-underline">
        <ArrowLeft size={16} aria-hidden /> Уведомления
      </Link>
      {isPending ? (
        <Skeleton rows={1} />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={(error as ApiError)?.status === 404 ? undefined : () => void refetch()} />
      ) : (
        <Card>
          <Kicker>
            {data.author} · {data.audience}
          </Kicker>
          <h1 className="m-0 mt-2 font-display text-lg font-semibold leading-snug">{data.title}</h1>
          <p className="m-0 mt-1 text-xs text-muted">{dateTime(data.publishedAt)}</p>
          <p className="m-0 mt-3 whitespace-pre-wrap break-words text-[15px] leading-relaxed">{data.body}</p>
        </Card>
      )}
    </div>
  );
}

// ── Профиль ───────────────────────────────────────────────────────────────────

function LogoutButton() {
  const { logout } = useAuth();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="ghost"
      busy={busy}
      className="w-full"
      onClick={() => {
        setBusy(true);
        void logout();
      }}
    >
      <LogOut size={16} aria-hidden /> Выйти из кабинета
    </Button>
  );
}

function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const options: { value: Theme; label: string; hint: string }[] = [
    { value: "night", label: "Ночь", hint: "тёмная" },
    { value: "day", label: "День", hint: "светлая, для яркого солнца" },
  ];
  return (
    <Card>
      <Kicker>Оформление</Kicker>
      <div role="radiogroup" aria-label="Тема оформления" className="mt-2 grid grid-cols-2 gap-1 rounded-[14px] bg-surface-2 p-1">
        {options.map((option) => (
          <button
            key={option.value}
            role="radio"
            aria-checked={theme === option.value}
            onClick={() => {
              applyTheme(option.value);
              setTheme(option.value);
            }}
            className={cx(
              "min-h-11 rounded-[11px] text-sm font-semibold",
              theme === option.value ? "mc-tab-active" : "text-muted",
            )}
          >
            {option.label}
            <span className="sr-only"> — {option.hint}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

export function ProfilePage() {
  const { user } = useAuth();
  if (!user?.student) return null;
  const s = user.student;
  const rows = [
    ["Факультет", s.faculty.name],
    ["Направление", `${s.program.code} ${s.program.name}`],
    ["Уровень", s.program.degree],
    ["Курс", String(s.year)],
    ["Группа", s.group],
    ["Год поступления", String(s.admissionYear)],
    ["Зачётная книжка", s.recordBook],
    ["Логин", user.username],
  ];
  return (
    <div className="grid gap-3">
      <PageTitle title="Профиль" />
      <Card>
        <div className="flex items-center gap-3">
          <span className="mc-grad grid size-14 shrink-0 place-items-center rounded-[18px] font-display text-lg font-bold">
            {user.initials}
          </span>
          <div className="min-w-0">
            <p className="m-0 text-lg font-bold leading-snug">{user.fullName}</p>
            <Badge tone="warn">
              <ShieldCheck size={12} aria-hidden /> Демонстрационный профиль
            </Badge>
          </div>
        </div>
        <dl className="m-0 mt-4 grid gap-2.5 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4">
              <dt className="shrink-0 text-muted">{label}</dt>
              <dd className="m-0 text-right font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <ThemeSwitch />
      <Card>
        <Kicker>О сервисе</Kicker>
        <p className="m-0 mt-1.5 text-sm text-muted">
          MGIMO Campus — конкурсный прототип для MGIMO AI Challenge 2026. Это не официальный сервис вуза. Имена,
          оценки, расписание и документы вымышлены.
        </p>
      </Card>
      <LogoutButton />
    </div>
  );
}

// ── Служебные страницы ───────────────────────────────────────────────────────

export function NotFoundPage() {
  const { user } = useAuth();
  return (
    <main className="mx-auto grid min-h-dvh w-full max-w-md content-center gap-4 px-4 py-8 text-center">
      <p className="m-0 font-display text-5xl font-bold text-muted">404</p>
      <h1 className="m-0 text-xl font-bold">Такой страницы нет</h1>
      <p className="m-0 text-sm text-muted">Возможно, ссылка устарела или в адресе опечатка.</p>
      <Link
        to={user ? homePath(user) : "/login"}
        className="mc-grad mx-auto inline-flex min-h-11 items-center rounded-xl px-5 text-sm font-bold no-underline"
      >
        {user ? "На главную" : "Ко входу"}
      </Link>
      <PrototypeNote />
    </main>
  );
}

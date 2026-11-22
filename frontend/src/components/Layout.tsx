import { Bell, CalendarDays, FileText, GraduationCap, ListChecks, Sun, User as UserIcon, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useNotifications } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { cx } from "./ui";

const NAV = [
  { to: "/today", label: "Сегодня", icon: Sun },
  { to: "/schedule", label: "Пары", icon: CalendarDays },
  { to: "/planner", label: "План", icon: ListChecks },
  { to: "/grades", label: "Оценки", icon: GraduationCap },
  { to: "/requests", label: "Заявки", icon: FileText },
];
// На компьютере в боковой колонке есть место и для профиля; на телефоне он открывается по аватару.
const SIDEBAR = [...NAV, { to: "/profile", label: "Профиль", icon: UserIcon }];

export function PrototypeNote({ className }: { className?: string }) {
  return (
    <p className={cx("m-0 text-center text-[10.5px] leading-snug text-muted", className)}>
      Конкурсный прототип · неофициальный сервис · данные вымышлены
    </p>
  );
}

/** Собственный знак проекта (не символика вуза): «маршрут» с точкой — отсылка к посадочному талону. */
export function Brand({ compact }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <img src="/mark.svg" alt="" width={34} height={34} className="rounded-[11px]" />
      <span className="leading-tight">
        <span className="block whitespace-nowrap font-display text-[14px] font-semibold tracking-tight">MGIMO Campus</span>
        {!compact && (
          <span className="block whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.08em] text-warn">
            конкурсный прототип
          </span>
        )}
      </span>
    </span>
  );
}

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

const iconTile = "relative grid size-11 place-items-center rounded-[13px] border border-line bg-surface text-text";

/** Каркас кабинета студента: шапка, плавающая нижняя панель на телефоне, боковая колонка на компьютере. */
export function StudentLayout() {
  const { user } = useAuth();
  const online = useOnline();
  const { pathname } = useLocation();
  const unread = useNotifications().data?.unreadCount ?? 0;

  useEffect(() => {
    // Блок, а не выражение: scrollTo() в новых браузерах возвращает Promise, а эффект не должен ничего возвращать.
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-6xl lg:gap-8 lg:px-6">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col py-6 lg:flex">
        <Link to="/today" className="px-2 text-text no-underline">
          <Brand />
        </Link>
        <nav className="mt-8 grid gap-1" aria-label="Разделы">
          {SIDEBAR.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cx(
                  "flex min-h-11 items-center gap-3 rounded-[14px] px-3 text-sm font-semibold no-underline",
                  isActive ? "mc-tab-active" : "text-muted hover:bg-surface hover:text-text",
                )
              }
            >
              <Icon size={18} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <PrototypeNote className="mt-auto px-2 text-left" />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line/60 bg-bg/80 px-4 py-2.5 backdrop-blur-md lg:px-0">
          <Link to="/today" className="text-text no-underline lg:invisible" aria-label="MGIMO Campus — на главную">
            <Brand />
          </Link>
          <div className="flex items-center gap-2.5">
            <Link
              to="/notifications"
              aria-label={unread ? `Уведомления, непрочитанных: ${unread}` : "Уведомления"}
              className={iconTile}
            >
              <Bell size={19} aria-hidden />
              {unread > 0 && (
                <span className="absolute -right-1.5 -top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-warn px-1 text-[11px] font-bold text-[#0a0c14] ring-2 ring-bg">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </Link>
            <Link
              to="/profile"
              aria-label={`Профиль: ${user?.fullName}`}
              className="mc-grad grid size-11 place-items-center rounded-[13px] font-display text-[12px] font-bold no-underline"
            >
              {user?.initials}
            </Link>
          </div>
        </header>

        {!online && (
          <div role="status" className="flex items-center gap-2 bg-warn-soft px-4 py-2 text-sm text-warn">
            <WifiOff size={16} aria-hidden /> Нет соединения. Показаны последние загруженные данные.
          </div>
        )}

        <main className="flex-1 px-4 pb-32 pt-4 lg:px-0 lg:pb-10 lg:pt-6">
          {/* «Сегодня» на компьютере раскладывается в две колонки, остальные разделы — одна читаемая колонка. */}
          <div className={pathname === "/today" ? "w-full" : "w-full max-w-2xl"}>
            <Outlet />
          </div>
        </main>
      </div>

      <nav aria-label="Разделы" className="fixed inset-x-0 bottom-0 z-20 px-2.5 pb-[max(6px,env(safe-area-inset-bottom))] lg:hidden">
        <div className="mc-dock mx-auto grid max-w-md grid-cols-5 gap-0.5 rounded-[22px] border border-line p-1.5 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cx(
                  "flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-2xl text-[10.5px] font-semibold no-underline",
                  isActive ? "mc-tab-active" : "text-muted",
                )
              }
            >
              <Icon size={20} aria-hidden />
              {label}
            </NavLink>
          ))}
        </div>
        <PrototypeNote className="pt-1" />
      </nav>
    </div>
  );
}

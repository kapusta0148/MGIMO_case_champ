import { BookOpen, CalendarDays, FileText, LayoutGrid, LogOut, Megaphone, ScrollText, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import type { Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand, PrototypeNote } from "./Layout";
import { cx } from "./ui";

type NavItem = { to: string; label: string; icon: typeof LayoutGrid; end?: boolean };

const DEAN_NAV: NavItem[] = [
  { to: "/staff", label: "Обзор", icon: LayoutGrid, end: true },
  { to: "/staff/requests", label: "Заявки", icon: FileText },
  { to: "/staff/schedule", label: "Расписание", icon: CalendarDays },
  { to: "/staff/announcements", label: "Объявления", icon: Megaphone },
];

const NAV: Record<Exclude<Role, "student">, NavItem[]> = {
  dean_staff: DEAN_NAV,
  admin: [
    ...DEAN_NAV,
    { to: "/admin/users", label: "Аккаунты", icon: Users },
    { to: "/admin/audit", label: "Журнал", icon: ScrollText },
  ],
  teacher: [{ to: "/teacher", label: "Мои курсы", icon: BookOpen, end: true }],
};

/** Каркас кабинета сотрудников: на телефоне разделы — прокручиваемая строка под шапкой. */
export function StaffLayout() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const [leaving, setLeaving] = useState(false);
  const items = user && user.role !== "student" ? NAV[user.role] : [];

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  const link = (item: NavItem, compact: boolean) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cx(
          "flex shrink-0 items-center gap-2 font-semibold no-underline",
          compact ? "min-h-10 rounded-full px-3.5 text-[13px]" : "min-h-11 rounded-[14px] px-3 text-sm",
          isActive ? "mc-tab-active" : "text-muted hover:bg-surface hover:text-text",
        )
      }
    >
      <item.icon size={compact ? 16 : 18} aria-hidden /> {item.label}
    </NavLink>
  );

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-6xl lg:gap-8 lg:px-6">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col py-6 lg:flex">
        <Link to={items[0]?.to ?? "/"} className="px-2 text-text no-underline">
          <Brand />
        </Link>
        <nav className="mt-8 grid gap-1" aria-label="Разделы">
          {items.map((item) => link(item, false))}
        </nav>
        <PrototypeNote className="mt-auto px-2 text-left" />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b border-line/60 bg-bg/85 backdrop-blur-md">
          <div className="flex items-center justify-between gap-3 px-4 py-2.5 lg:px-0">
            <Link to={items[0]?.to ?? "/"} className="text-text no-underline lg:hidden">
              <Brand />
            </Link>
            <div className="ml-auto flex min-w-0 items-center gap-2.5">
              <div className="hidden min-w-0 text-right sm:block">
                <div className="truncate text-sm font-semibold">{user?.fullName}</div>
                <div className="truncate text-xs text-muted">{user?.roleLabel}</div>
              </div>
              <span className="mc-grad grid size-11 shrink-0 place-items-center rounded-[13px] font-display text-[12px] font-bold">
                {user?.initials}
              </span>
              <button
                aria-label="Выйти из кабинета"
                disabled={leaving}
                onClick={() => {
                  setLeaving(true);
                  void logout();
                }}
                className="grid size-11 shrink-0 place-items-center rounded-[13px] border border-line bg-surface text-text"
              >
                <LogOut size={18} aria-hidden />
              </button>
            </div>
          </div>
          {items.length > 1 && (
            <nav aria-label="Разделы" className="flex gap-1.5 overflow-x-auto px-4 pb-2.5 lg:hidden">
              {items.map((item) => link(item, true))}
            </nav>
          )}
        </header>

        <main className="flex-1 px-4 pb-16 pt-4 lg:px-0 lg:pt-6">
          <div className="w-full max-w-3xl">
            <Outlet />
          </div>
        </main>
        <PrototypeNote className="pb-4 lg:hidden" />
      </div>
    </div>
  );
}

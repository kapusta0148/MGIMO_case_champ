// Сервер возвращает московское время (+03:00); расписание отображается без пересчёта в часовой пояс устройства.

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];
const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const WEEKDAYS_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

/** "2026-11-16T10:30:00+03:00" -> "10:30" */
export const time = (iso: string) => iso.slice(11, 16);

export const timeRange = (start: string, end: string) => `${time(start)}–${time(end)}`;

function parts(isoDate: string) {
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return { y, m, d, weekday: new Date(Date.UTC(y, m - 1, d)).getUTCDay() };
}

/** "2026-11-16" -> "16 ноября" */
export function dayMonth(isoDate: string) {
  const { m, d } = parts(isoDate);
  return `${d} ${MONTHS[m - 1]}`;
}

/** "2026-11-16" -> "понедельник, 16 ноября" */
export function fullDate(isoDate: string) {
  return `${WEEKDAYS[parts(isoDate).weekday]}, ${dayMonth(isoDate)}`;
}

/** "2026-11-16" -> "пн, 16 ноября" */
export function shortDate(isoDate: string) {
  return `${WEEKDAYS_SHORT[parts(isoDate).weekday]}, ${dayMonth(isoDate)}`;
}

/** "2026-11-16T10:30:00+03:00" -> "16 ноября, 10:30" */
export const dateTime = (iso: string) => `${dayMonth(iso)}, ${time(iso)}`;

export function addDays(isoDate: string, days: number) {
  const { y, m, d } = parts(isoDate);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Сколько осталось до занятия: "через 42 мин", "через 2 ч 10 мин", "завтра в 09:00". */
export function untilText(minutes: number, startsAt: string, isToday: boolean) {
  if (!isToday) return `${shortDate(startsAt)} в ${time(startsAt)}`;
  if (minutes < 1) return "начинается";
  if (minutes < 60) return `через ${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `через ${hours} ч ${rest} мин` : `через ${hours} ч`;
}

/** Относительный срок дедлайна: "сегодня, 23:59", "завтра, 23:59", "пт, 20 ноября, 23:59". */
export function dueText(dueAt: string, today: string) {
  const date = dueAt.slice(0, 10);
  if (date === today) return `сегодня, ${time(dueAt)}`;
  if (date === addDays(today, 1)) return `завтра, ${time(dueAt)}`;
  return `${shortDate(date)}, ${time(dueAt)}`;
}

export function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

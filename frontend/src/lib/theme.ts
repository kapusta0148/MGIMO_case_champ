// Тема оформления — удобство конкретного устройства, поэтому хранится в браузере, а не на сервере.
// «Ночь» по умолчанию (концепция A), «День» — для яркого солнца и тех, кто предпочитает светлый фон.

export type Theme = "night" | "day";
const KEY = "mc.theme";
const META_COLOR: Record<Theme, string> = { night: "#0a0c14", day: "#f3f4fa" };

export function readTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "day" ? "day" : "night";
  } catch {
    return "night";
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", META_COLOR[theme]);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* приватный режим: тема просто не запомнится */
  }
}

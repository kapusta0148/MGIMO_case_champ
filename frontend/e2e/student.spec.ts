import { expect, test, type Page } from "@playwright/test";
import { E2E } from "../playwright.config";

type Account = { username: string; password: string };

async function login(page: Page, account: Account) {
  await page.getByLabel("Логин").fill(account.username);
  await page.getByLabel("Пароль").fill(account.password);
  await page.getByRole("button", { name: "Войти" }).click();
}

/** Ширина документа не больше окна: нет горизонтальной прокрутки. */
async function expectNoHorizontalScroll(page: Page) {
  const { doc, view } = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth,
    view: document.documentElement.clientWidth,
  }));
  expect(doc, "горизонтальная прокрутка").toBeLessThanOrEqual(view);
}

async function createCertificateRequest(page: Page): Promise<{ id: string; number: string }> {
  await page.goto("/requests/new");
  await page.getByRole("button", { name: /Справка об обучении/ }).click();
  await page.getByRole("button", { name: "Отправить заявку" }).click();
  await expect(page.getByText("Заполните это поле.")).toBeVisible(); // пустая форма не уходит
  await page.getByLabel("Куда предоставляется").selectOption("bank");
  await page.getByLabel(/Комментарий/).fill("Проверка e2e: справка для банка.");
  await page.getByRole("button", { name: "Отправить заявку" }).click();
  await expect(page).toHaveURL(/\/requests\/\d+$/);
  await expect(page.getByRole("status")).toContainText("Заявка отправлена");
  const number = (await page.getByText(/MC-\d{4}-\d{5}/).first().textContent())!.match(/MC-\d{4}-\d{5}/)![0];
  return { id: page.url().split("/").pop()!, number };
}

test("главный сценарий: перенос из уведомления, заявка сохраняется после обновления и повторного входа", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText(/Конкурсный прототип/).first()).toBeVisible();
  await login(page, E2E.student1);

  // «Сегодня»: талон следующей пары и строка переноса.
  await expect(page).toHaveURL(/\/today$/);
  await expect(page.getByRole("heading", { name: "Привет, Мира" })).toBeVisible();
  await expect(page.getByText("Следующая пара")).toBeVisible();
  const changeOnToday = page.getByRole("region", { name: "Изменения в расписании" });
  await expect(changeOnToday).toBeVisible();
  await expectNoHorizontalScroll(page);

  // Уведомление о переносе ведёт к тому же занятию в расписании.
  await page.getByRole("link", { name: /Уведомления/ }).click();
  const note = page.locator("article").filter({ hasText: /Перенос занятия|Смена аудитории/ }).first();
  await expect(note).toBeVisible();
  const newSlot = (await note.locator("strong").first().textContent())!.trim(); // «14:00 · ауд. 1126»
  await note.getByRole("button", { name: "Открыть занятие в расписании" }).click();
  await expect(page).toHaveURL(/\/schedule\?date=\d{4}-\d{2}-\d{2}&lesson=\d+/);
  const lessonId = new URL(page.url()).searchParams.get("lesson");
  const card = page.locator(`#lesson-${lessonId}`);
  await expect(card).toBeVisible();
  await expect(card).toContainText(/Перенос|Другая аудитория/); // метка зависит от того, менялось ли время
  await expect(card).toContainText(newSlot); // одно и то же состояние в уведомлении и расписании
  await expectNoHorizontalScroll(page);

  // Заявка: создание, обновление страницы, выход, возврат по ссылке после входа.
  const created = await createCertificateRequest(page);
  await expectNoHorizontalScroll(page);
  await page.reload();
  await expect(page.getByText(created.number)).toBeVisible();
  await expect(page.getByText("Создана").first()).toBeVisible();

  await page.goto("/profile");
  await page.getByRole("button", { name: "Выйти из кабинета" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto(`/requests/${created.id}`);
  await expect(page).toHaveURL(/\/login$/); // без входа личная страница не открывается
  await login(page, E2E.student1);
  await expect(page).toHaveURL(new RegExp(`/requests/${created.id}$`)); // вернулись туда, куда шли
  await expect(page.getByText(created.number)).toBeVisible();

  await page.goto("/requests");
  await expect(page.getByText(created.number)).toBeVisible();
});

test("второй студент видит свои данные и не может открыть чужую заявку", async ({ browser }) => {
  const first = await browser.newPage();
  await first.goto("/login");
  await login(first, E2E.student1);
  await expect(first).toHaveURL(/\/today$/);
  const created = await createCertificateRequest(first);

  // Отдельный контекст — как другое устройство с другим студентом.
  const context = await browser.newContext();
  const second = await context.newPage();
  await second.goto("/login");
  await login(second, E2E.student2);
  await expect(second.getByRole("heading", { name: "Привет, Тимур" })).toBeVisible();

  await second.goto("/profile");
  await expect(second.getByText("МЭО-3-07")).toBeVisible();
  await expect(second.getByText("Северцева")).toHaveCount(0);

  await second.goto("/requests");
  await expect(second.getByRole("heading", { name: "Заявки" })).toBeVisible();
  await expect(second.getByText(created.number)).toHaveCount(0);

  await second.goto(`/requests/${created.id}`);
  await expect(second.getByRole("alert")).toContainText("Заявка не найдена");
  await expect(second.getByText(created.number)).toHaveCount(0);

  const api = await second.evaluate(async (id) => (await fetch(`/api/me/requests/${id}`)).status, created.id);
  expect(api).toBe(404);

  await first.goto("/grades");
  await second.goto("/grades");
  await expect(first.getByText("Политология").first()).toBeVisible();
  await expect(second.getByText("Эконометрика").first()).toBeVisible();
  await expect(second.getByText("Политология")).toHaveCount(0);
  await context.close();
});

test("все разделы студента без горизонтальной прокрутки", async ({ page }) => {
  await page.goto("/login");
  await expectNoHorizontalScroll(page);
  await login(page, E2E.student2);
  await expect(page).toHaveURL(/\/today$/);
  for (const path of [
    "/today",
    "/schedule",
    "/schedule?view=day",
    "/schedule?view=deadlines",
    "/planner",
    "/grades",
    "/requests",
    "/requests/new",
    "/notifications",
    "/profile",
    "/no-such-page",
  ]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await page.locator("details").evaluateAll((items) => items.forEach((d) => d.setAttribute("open", "")));
    await expectNoHorizontalScroll(page);
  }
});

test("сотрудник не попадает в кабинет студента", async ({ page }) => {
  await page.goto("/login");
  await login(page, { username: "dean", password: E2E.staffPassword });
  await expect(page).toHaveURL(/\/staff$/);
  await page.goto("/today");
  await expect(page).toHaveURL(/\/staff$/);
  const status = await page.evaluate(async () => (await fetch("/api/me/dashboard")).status);
  expect(status).toBe(403);
});

test("планировщик: предложение попадает в задачи только по нажатию", async ({ page }) => {
  await page.goto("/login");
  await login(page, E2E.student1);
  await expect(page).toHaveURL(/\/today$/);
  await page.getByRole("link", { name: /План на неделю|Окно/ }).first().click();
  await expect(page).toHaveURL(/\/planner$/);
  await expect(page.getByRole("heading", { name: "План на неделю" })).toBeVisible();
  await expect(page.getByText("алгоритм по правилам")).toBeVisible();
  await expectNoHorizontalScroll(page);

  const tasks = page.getByRole("region", { name: /Мои задачи/ }).or(page.locator("section[aria-labelledby=my-tasks]"));
  const before = await tasks.locator("li").count();
  const suggestion = page.locator("article").filter({ has: page.getByRole("button", { name: "Добавить в мои задачи" }) }).first();
  const title = (await suggestion.locator("p").first().textContent())!.trim();
  await suggestion.getByText("Почему так?").click();
  await expect(suggestion.getByText(/^Срок — /)).toBeVisible();
  await suggestion.getByRole("button", { name: "Добавить в мои задачи" }).click();

  const row = tasks.locator("li").filter({ hasText: title });
  await expect(row).toBeVisible();
  await expect(row).toContainText("из плана");
  expect(await tasks.locator("li").count()).toBe(before + 1);

  await page.reload(); // задача хранится на сервере
  await expect(row).toBeVisible();
  await row.getByRole("checkbox").click();
  await expect(row.getByRole("checkbox")).toHaveAttribute("aria-checked", "true");
  await row.getByRole("button", { name: /Удалить/ }).click();
  await expect(row).toHaveCount(0);
  await expectNoHorizontalScroll(page);
});

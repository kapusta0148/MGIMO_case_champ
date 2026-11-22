import { expect, test, type Browser, type Page } from "@playwright/test";
import { E2E } from "../playwright.config";

async function loginAs(browser: Browser, username: string, password: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/login");
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
  return page;
}

async function expectNoHorizontalScroll(page: Page) {
  const { doc, view } = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth,
    view: document.documentElement.clientWidth,
  }));
  expect(doc, "горизонтальная прокрутка").toBeLessThanOrEqual(view);
}

test("деканат одобряет заявку — студент видит статус, комментарий и уведомление", async ({ browser }) => {
  const student = await loginAs(browser, E2E.student1.username, E2E.student1.password);
  await student.goto("/requests/new");
  await student.getByRole("button", { name: /Справка об успеваемости/ }).click();
  await student.getByLabel("Период").selectOption("last_term");
  await student.getByRole("button", { name: "Отправить заявку" }).click();
  await expect(student).toHaveURL(/\/requests\/\d+$/);
  const number = (await student.getByText(/MC-\d{4}-\d{5}/).first().textContent())!.match(/MC-\d{4}-\d{5}/)![0];

  const dean = await loginAs(browser, "dean", E2E.staffPassword);
  await expect(dean).toHaveURL(/\/staff$/);
  await expectNoHorizontalScroll(dean);
  await dean.goto("/staff/requests");
  await dean.getByPlaceholder("Номер, тема или ФИО").fill(number);
  await dean.getByRole("link", { name: new RegExp(number) }).click();
  await expect(dean.getByText("Северцева Мира Олеговна").first()).toBeVisible();
  await expectNoHorizontalScroll(dean);
  await dean.getByRole("button", { name: "Взять в работу" }).click();
  await expect(dean.getByRole("status")).toContainText("на рассмотрении");
  await dean.getByRole("button", { name: "Отклонить" }).click();
  await expect(dean.getByRole("alert")).toContainText("почему отказано"); // без комментария нельзя
  await dean.getByLabel("Комментарий студенту").fill("Выписка готова, кабинет 2010.");
  await dean.getByRole("button", { name: "Одобрить" }).click();
  await expect(dean.getByRole("status")).toContainText("одобрена");

  await student.reload();
  await expect(student.getByText("Одобрена").first()).toBeVisible();
  await expect(student.getByText("Выписка готова, кабинет 2010.")).toBeVisible();
  await student.goto("/notifications");
  await expect(student.getByText(`Заявка ${number}: одобрена`)).toBeVisible();
});

test("деканат меняет аудиторию — уведомление у студента; преподаватель ставит балл", async ({ browser }) => {
  const room = `E2E-${Math.floor(Math.random() * 9000 + 1000)}`;
  const dean = await loginAs(browser, "dean", E2E.staffPassword);
  await dean.goto("/staff/schedule");
  const group = dean.getByLabel("Группа");
  const value = await group.locator("option", { hasText: "МО-2-03" }).getAttribute("value");
  await group.selectOption(value!);
  await dean.getByRole("button", { name: "Изменить занятие" }).first().click();
  await dean.getByLabel("Аудитория").fill(room);
  await dean.getByLabel("Причина").fill("Проверка e2e: ремонт в аудитории.");
  await expectNoHorizontalScroll(dean);
  await dean.getByRole("button", { name: "Перенести" }).click();
  await expect(dean.getByRole("status")).toContainText("Уведомлено студентов: 1");

  const student = await loginAs(browser, E2E.student1.username, E2E.student1.password);
  await student.goto("/notifications");
  await expect(student.getByText(`ауд. ${room}`).first()).toBeVisible();

  const teacher = await loginAs(browser, "teacher", E2E.teacherPassword);
  await expect(teacher).toHaveURL(/\/teacher$/);
  await teacher.getByRole("link", { name: /Теория международных отношений/ }).click();
  const input = teacher.locator('input[placeholder="—"]:enabled').first();
  await expect(input).toBeVisible();
  const score = (await input.inputValue()) === "88" ? "87" : "88"; // всегда новое значение — тест не зависит от порядка
  await input.fill(score);
  await input.press("Enter");
  await expect(teacher.getByLabel("сохранено").first()).toBeVisible();
  await expectNoHorizontalScroll(teacher);

  await student.reload();
  await expect(student.getByText("Новая оценка: Теория международных отношений").first()).toBeVisible();
  await expect(student.getByText(new RegExp(`— ${score} из 100`)).first()).toBeVisible();
});

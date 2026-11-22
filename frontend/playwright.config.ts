import { defineConfig } from "@playwright/test";

// Сквозные тесты идут против настоящего Flask + PostgreSQL на отдельной базе campus_e2e.
// Перед запуском: `docker compose up -d` (база) и `npm run build` (Flask раздаёт собранный интерфейс).
// Пароли ниже — только для локальной e2e-базы, которую скрипт пересоздаёт при каждом запуске.

// Внешний адрес (E2E_BASE_URL) — проверка размещённой версии: свой сервер не запускается,
// пароли берутся из переменных окружения (их кладёт скрипт ops/deploy/check_production.sh).
const remote = process.env.E2E_BASE_URL;

export const E2E = {
  port: 5002,
  student1: { username: "student1", password: process.env.E2E_PASSWORD_STUDENT1 ?? "e2e-student1-pass" },
  student2: { username: "student2", password: process.env.E2E_PASSWORD_STUDENT2 ?? "e2e-student2-pass" },
  staffPassword: process.env.E2E_PASSWORD_DEAN ?? "e2e-staff-pass",
  teacherPassword: process.env.E2E_PASSWORD_TEACHER ?? "e2e-staff-pass",
};

const databaseUrl =
  process.env.E2E_DATABASE_URL ?? "postgresql+psycopg://campus:campus_local_only@127.0.0.1:5433/campus_e2e";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 30_000,
  use: {
    baseURL: remote ?? `http://localhost:${E2E.port}`,
    channel: "chrome", // установленный Google Chrome, без скачивания отдельного браузера
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "phone-360", use: { viewport: { width: 360, height: 780 }, hasTouch: true, isMobile: true } },
    { name: "phone-390", use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
  ],
  webServer: remote
    ? undefined
    : {
        command: `sh -c "cd ../backend && .venv/bin/python scripts/e2e_prepare.py && exec .venv/bin/flask run --port ${E2E.port}"`,
        url: `http://localhost:${E2E.port}/api/health`,
        reuseExistingServer: false,
        timeout: 90_000,
        stdout: "ignore",
        env: {
          ...process.env,
          APP_ENV: "development",
          FLASK_APP: "wsgi:app",
          DATABASE_URL: databaseUrl,
          E2E_PASSWORD_STUDENT1: E2E.student1.password,
          E2E_PASSWORD_STUDENT2: E2E.student2.password,
          E2E_PASSWORD_STAFF: E2E.staffPassword,
        } as Record<string, string>,
      },
});

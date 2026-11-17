# Сторонние материалы и лицензии

Версии зафиксированы в `backend/requirements.txt` и `frontend/package-lock.json`. Лицензии взяты из метаданных установленных пакетов 17.11.2026.

## Попадают в браузер пользователя

| Пакет | Версия | Лицензия | Назначение |
|---|---|---|---|
| react, react-dom | 19.3.1 | MIT | интерфейс |
| react-router-dom | 7.18.5 | MIT | адреса страниц |
| @tanstack/react-query | 5.107.1 | MIT | загрузка и кеш данных |
| lucide-react | 1.73.0 | ISC | иконки |
| @fontsource-variable/onest (шрифт Onest) | 5.3.1 | SIL OFL 1.1 | основной текст |
| @fontsource-variable/unbounded (шрифт Unbounded) | 5.3.0 | SIL OFL 1.1 | заголовки и время |

## Работают на сервере

| Пакет | Версия | Лицензия |
|---|---|---|
| Flask | 3.1.3 | BSD-3-Clause |
| Werkzeug | 3.1.9 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| itsdangerous | 2.2.0 | BSD-3-Clause |
| click | 8.5.1 | BSD-3-Clause |
| Flask-SQLAlchemy | 3.1.1 | BSD-3-Clause |
| SQLAlchemy | 2.1.8 | MIT |
| Flask-Migrate | 4.1.0 | MIT |
| alembic | 1.20.1 | MIT |
| Mako | 1.4.3 | MIT |
| psycopg, psycopg-binary | 3.3.9 | LGPL-3.0 (используется как библиотека без изменений) |
| argon2-cffi | 25.1.0 | MIT |
| Flask-WTF, WTForms | 1.3.0, 3.3.2 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| gunicorn | 27.0.1 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| PostgreSQL (образ `postgres:17-alpine`) | 17 | PostgreSQL License |

## Только для разработки и тестов

| Пакет | Версия | Лицензия |
|---|---|---|
| vite | 8.3.8 | MIT |
| @vitejs/plugin-react | 6.3.0 | MIT |
| tailwindcss, @tailwindcss/vite | 4.3.5 | MIT |
| typescript | 7.0.2 | Apache-2.0 |
| @types/react, @types/react-dom | 19.3.0 | MIT |
| @playwright/test | 1.65.1 | Apache-2.0 |
| pytest | 9.2.0 | MIT |
| ruff | 0.17.5 | MIT |

## Собственные материалы

- Знак MGIMO Campus (`frontend/public/mark.svg`) нарисован для проекта: градиентный квадрат с «маршрутом» и точкой. Не повторяет символику вуза.
- Все имена, оценки, номера зачёток, заявки и объявления придуманы (`backend/app/seeds/data.py`).
- Название и общие реалии вуза используются как контекст конкурса. Официальный логотип не используется.

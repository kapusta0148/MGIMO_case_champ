#!/usr/bin/env bash
# Сквозная проверка размещённой версии теми же тестами Playwright, что и локально.
# Тесты создают проверочные заявки, поэтому после них демо-данные пересоздаются
# с прежними паролями (flask seed --reset --keep-passwords) — выданные жюри логины не меняются.
# Запуск из корня репозитория: bash ops/deploy/check_production.sh [--keep-test-data]
set -euo pipefail
cd "$(dirname "$0")/../.."
. ops/deploy/config.sh

CREDS="$PWD/backend/instance/production_demo_credentials.json"
[ -f "$CREDS" ] || { echo "Нет $CREDS — сначала выполните ops/deploy/deploy.sh" >&2; exit 1; }
pw() { python3 -c "import json,sys; print(json.load(open('$CREDS'))[sys.argv[1]])" "$1"; }

status=0
(
  cd frontend
  E2E_BASE_URL="https://$SITE_HOST" \
  E2E_PASSWORD_STUDENT1="$(pw student1)" \
  E2E_PASSWORD_STUDENT2="$(pw student2)" \
  E2E_PASSWORD_DEAN="$(pw dean)" \
  E2E_PASSWORD_TEACHER="$(pw teacher)" \
  npx playwright test
) || status=$?

if [ "${1:-}" != "--keep-test-data" ]; then
  echo "Пересоздание демо-данных на сервере (пароли сохраняются)…"
  ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$SERVER_USER@$SERVER_IP" \
    "sudo -u campus bash -c 'set -a; . /etc/campus/campus.env; set +a; cd /opt/campus/backend; FLASK_APP=wsgi:app /opt/campus/venv/bin/flask seed --reset --yes --keep-passwords'"
fi
exit $status

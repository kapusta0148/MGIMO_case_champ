#!/usr/bin/env bash
# Выкладка MGIMO Campus на сервер. Запуск из корня репозитория: bash ops/deploy/deploy.sh
# Первый запуск настраивает сервер и засевает демо-данные; повторные — только обновляют код.
set -euo pipefail
cd "$(dirname "$0")/../.."
. ops/deploy/config.sh

SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o ConnectTimeout=20)
remote() { ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" "$@"; }
push() { rsync -az --delete -e "ssh ${SSH_OPTS[*]}" "$@"; }
# Команда Flask от имени пользователя службы с production-окружением.
as_app() { remote "sudo -u campus bash -c 'set -a; . /etc/campus/campus.env; set +a; cd /opt/campus/backend; FLASK_APP=wsgi:app /opt/campus/venv/bin/flask $*'"; }

echo "1/6 Сборка интерфейса"
(cd frontend && npm run build >/dev/null)

echo "2/6 Настройка сервера"
push ops/deploy/ "$SERVER_USER@$SERVER_IP:/tmp/campus-setup/"
remote "sudo bash /tmp/campus-setup/server_setup.sh '$SITE_HOST' '$SERVER_IP'" 2>&1 | grep -vE '^\s*$|^\{"level":"(info|warn)"' || true

echo "3/6 Копирование кода"
push --exclude .venv --exclude instance --exclude uploads --exclude __pycache__ \
  --exclude .pytest_cache --exclude .ruff_cache --exclude tests \
  backend/ "$SERVER_USER@$SERVER_IP:/opt/campus/backend/"
push frontend/dist/ "$SERVER_USER@$SERVER_IP:/opt/campus/frontend/dist/"

echo "4/6 Зависимости Python"
remote "set -e; cd /opt/campus; [ -x venv/bin/python ] || python3 -m venv venv; \
  venv/bin/pip install -q --disable-pip-version-check -r backend/requirements.txt; \
  venv/bin/python -m compileall -q backend/app >/dev/null"

echo "5/6 Миграции и демо-данные"
as_app "db upgrade" 2>&1 | grep -vE '^INFO  \[alembic.runtime.migration\] (Context|Will assume)' || true
USERS=$(remote "sudo -u postgres psql -tAc 'select count(*) from users' campus" 2>/dev/null || echo 0)
if [ "${USERS:-0}" = "0" ]; then
  as_app "seed"
  install -d -m 700 backend/instance
  remote "sudo cat /opt/campus/backend/instance/demo_credentials.json" > backend/instance/production_demo_credentials.json
  chmod 600 backend/instance/production_demo_credentials.json
  echo "   Пароли демо-аккаунтов сохранены в backend/instance/production_demo_credentials.json (вне Git)"
fi

echo "6/6 Перезапуск и проверка"
remote "sudo systemctl restart campus && sleep 2 && systemctl is-active campus"
for i in $(seq 1 30); do
  if curl -fsS --max-time 10 "https://$SITE_HOST/api/health" >/dev/null 2>&1; then
    echo "   Готово: https://$SITE_HOST"
    exit 0
  fi
  sleep 3
done
echo "   HTTPS пока не отвечает — смотрите: ssh ... 'sudo journalctl -u caddy -u campus -n 50'" >&2
exit 1

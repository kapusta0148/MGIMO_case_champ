#!/usr/bin/env bash
# Настройка сервера Ubuntu 24.04 для MGIMO Campus. Идемпотентна: повторный запуск ничего не ломает.
# Запускается из deploy.sh командой `sudo bash server_setup.sh <SITE_HOST> <SERVER_IP>`.
# Все секреты (пароль базы, SECRET_KEY) создаются здесь, на сервере, и никуда не передаются.
set -euo pipefail

SITE_HOST="$1"
SERVER_IP="$2"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_USER="${SUDO_USER:-deploy}"

log() { printf '\n== %s\n' "$*"; }

log "Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq --no-install-recommends python3-venv postgresql caddy ufw rsync curl ca-certificates openssl >/dev/null

log "Подкачка 1 ГБ (страховка для 2 ГБ памяти)"
if ! swapon --show=NAME --noheadings | grep -q '^/swapfile$'; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

log "Пользователь и каталоги"
id campus >/dev/null 2>&1 || useradd --system --home-dir /var/lib/campus --shell /usr/sbin/nologin campus
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 755 /opt/campus /opt/campus/backend /opt/campus/frontend
install -d -o campus -g campus -m 700 /opt/campus/backend/instance
install -d -o campus -g campus -m 750 /var/lib/campus /var/lib/campus/uploads
install -d -o postgres -g postgres -m 750 /var/backups/campus
install -d -o root -g campus -m 750 /etc/campus
install -d -o caddy -g caddy -m 755 /var/log/caddy

log "PostgreSQL и файл окружения"
systemctl enable --now postgresql >/dev/null 2>&1
if [ ! -f /etc/campus/campus.env ]; then
  DB_PASS="$(openssl rand -hex 24)"
  if sudo -u postgres psql -tAc "select 1 from pg_roles where rolname='campus'" | grep -q 1; then
    sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c "alter role campus with login password '${DB_PASS}'"
  else
    sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c "create role campus login password '${DB_PASS}'"
  fi
  sudo -u postgres psql -tAc "select 1 from pg_database where datname='campus'" | grep -q 1 \
    || sudo -u postgres createdb -O campus -E UTF8 campus
  umask 027
  cat > /etc/campus/campus.env <<ENV
APP_ENV=production
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=postgresql+psycopg://campus:${DB_PASS}@127.0.0.1:5432/campus
TRUST_PROXY=1
SESSION_COOKIE_SECURE=1
UPLOAD_DIR=/var/lib/campus/uploads
FRONTEND_DIST=/opt/campus/frontend/dist
ENV
  chown root:campus /etc/campus/campus.env
  chmod 640 /etc/campus/campus.env
fi

log "Брандмауэр: только SSH, HTTP и HTTPS"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | head -1

log "Службы systemd"
install -m 644 "$SRC"/systemd/*.service "$SRC"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable campus.service campus-refresh.timer campus-backup.timer >/dev/null
systemctl start campus-refresh.timer campus-backup.timer

log "Caddy (HTTPS для ${SITE_HOST})"
sed -e "s/SITE_HOST/${SITE_HOST}/g" -e "s/SERVER_IP/${SERVER_IP}/g" "$SRC/Caddyfile.template" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
  || { caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; exit 1; }
systemctl enable caddy >/dev/null
systemctl reload-or-restart caddy

log "Готово"

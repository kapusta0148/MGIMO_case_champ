# Общие параметры деплоя. Секретов здесь нет: пароли и ключи создаются на сервере.
SERVER_IP="${SERVER_IP:-153.51.170.126}"
SERVER_USER="${SERVER_USER:-deploy}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/mgimo_campus_deploy}"
# Без собственного домена используем имя sslip.io: оно указывает на IP и позволяет выпустить HTTPS.
SITE_HOST="${SITE_HOST:-$(echo "$SERVER_IP" | tr . -).sslip.io}"
APP_DIR=/opt/campus

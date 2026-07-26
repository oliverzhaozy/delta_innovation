#!/usr/bin/env bash
# One-shot (re-runnable) server setup for the coyadmin VM — Debian 12 on GCE.
# Expects, before running as root:
#   /tmp/delta-app.tar.gz    sanitized release tarball (see DEPLOY.md build step)
#   /tmp/deploy/             this directory's files
#   /etc/duckdns/token       DuckDNS token, mode 600
#   /etc/delta/age.recipient age PUBLIC key, mode 644
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

[ -f /etc/duckdns/token ] || { echo "missing /etc/duckdns/token" >&2; exit 1; }
[ -f /etc/delta/age.recipient ] || { echo "missing /etc/delta/age.recipient" >&2; exit 1; }

timedatectl set-timezone Asia/Singapore

apt-get update -qq
apt-get install -yqq python3-venv sqlite3 age ufw unattended-upgrades apt-transport-https curl gnupg

# Caddy from its official repo — Debian's own package lags behind.
if [ ! -f /etc/apt/sources.list.d/caddy-stable.list ]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
fi
apt-get install -yqq caddy

# GCP's VPC firewall already filters, but ufw keeps the posture visible and
# host-local per TECH_PLAN. 22 must be allowed BEFORE enabling — we are on it.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# Non-login service user; DB dir 700 (WAL needs directory write; nobody else
# needs to read it).
id delta >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/delta --shell /usr/sbin/nologin delta
install -d -m 700 -o delta -g delta /var/lib/delta

# Fresh app tree every deploy; the tarball is the sanitized whitelist build,
# so nothing stale (or sensitive) can linger from a previous release.
rm -rf /opt/delta/app
install -d -o delta -g delta /opt/delta/app
tar -xzf /tmp/delta-app.tar.gz -C /opt/delta/app
chown -R delta:delta /opt/delta/app

[ -x /opt/delta/venv/bin/python ] || sudo -u delta python3 -m venv /opt/delta/venv
sudo -u delta /opt/delta/venv/bin/pip install --quiet --upgrade pip
sudo -u delta /opt/delta/venv/bin/pip install --quiet -r /opt/delta/app/requirements.txt gunicorn

# Env file survives redeploys so the SECRET_KEY (and sessions) are stable.
if [ ! -f /etc/delta/env ]; then
    secret=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > /etc/delta/env <<EOF
APP_CONFIG=prod
FLASK_APP=wsgi.py
SECRET_KEY=$secret
DATABASE_URL=sqlite:////var/lib/delta/delta.db
TZ=Asia/Singapore
EOF
    chmod 600 /etc/delta/env
fi

# Migrations + demo seed. Both seed commands skip rows that already exist.
# Explicit env: gunicorn never reads .flaskenv, and the tarball excludes it
# (its FLASK_DEBUG=1 would trip ProdConfig's refuse-to-boot guard).
run_flask() {
    (cd /opt/delta/app && sudo -u delta env $(grep -v '^#' /etc/delta/env | xargs) \
        /opt/delta/venv/bin/python -m flask "$@")
}
run_flask db upgrade
run_flask seed-people seed/demo_people.csv
run_flask seed-holidays seed/holidays_sg.csv

install -m 755 /tmp/deploy/delta-backup.sh /usr/local/bin/delta-backup.sh
install -m 755 /tmp/deploy/duckdns-update.sh /usr/local/bin/duckdns-update.sh
install -m 644 /tmp/deploy/delta.service /etc/systemd/system/delta.service
install -m 644 /tmp/deploy/delta-backup.service /etc/systemd/system/delta-backup.service
install -m 644 /tmp/deploy/delta-backup.timer /etc/systemd/system/delta-backup.timer
install -m 644 /tmp/deploy/duckdns.service /etc/systemd/system/duckdns.service
install -m 644 /tmp/deploy/duckdns.timer /etc/systemd/system/duckdns.timer
install -m 644 /tmp/deploy/Caddyfile /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl enable --now delta-backup.timer duckdns.timer
systemctl enable delta.service
systemctl restart delta.service
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "SETUP_DONE"

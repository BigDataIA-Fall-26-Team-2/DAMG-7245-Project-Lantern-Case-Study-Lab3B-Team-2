#!/usr/bin/env bash
# Run as root on Ubuntu 24.04 after copying the release to /opt/askpanel/cs4b.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y python3-venv nginx
id askpanel >/dev/null 2>&1 || useradd --system --home /opt/askpanel --shell /usr/sbin/nologin askpanel
cd /opt/askpanel/cs4b
python3 -m venv /opt/askpanel/venv
/opt/askpanel/venv/bin/pip install -r deploy/requirements.txt
/opt/askpanel/venv/bin/python tools/build_db.py
mkdir -p logs outputs/cache
chown -R askpanel:askpanel /opt/askpanel
chmod -R o+rX frontend/dist
if [ ! -f /etc/askpanel.env ]; then install -m 600 /dev/null /etc/askpanel.env; fi
install -m 644 deploy/askpanel.service /etc/systemd/system/askpanel.service
install -m 644 deploy/nginx.conf /etc/nginx/sites-available/askpanel
ln -sfn /etc/nginx/sites-available/askpanel /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now askpanel nginx
systemctl restart askpanel nginx
curl --fail --retry 10 --retry-connrefused --retry-delay 2 http://127.0.0.1:8000/health

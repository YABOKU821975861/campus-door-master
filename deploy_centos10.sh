#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/campus_door_master}"
SERVICE_NAME="campus-door-master"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root: sudo bash deploy_centos10.sh"
  exit 1
fi

echo "[1/7] Installing system packages..."
dnf install -y python3 python3-pip python3-devel gcc

echo "[2/7] Creating service account..."
if ! id campusdoor >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /sbin/nologin campusdoor
fi

echo "[3/7] Preparing directories..."
mkdir -p "$APP_DIR/storage" "$APP_DIR/logs"

echo "[4/7] Creating virtual environment..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/campus-door-master.env" ]]; then
  cp "$APP_DIR/campus-door-master.env.example" "$APP_DIR/campus-door-master.env"
  echo "Created $APP_DIR/campus-door-master.env"
  echo "Edit it before starting the service."
fi

echo "[5/7] Installing systemd unit..."
install -m 0644 "$APP_DIR/campus-door-master.centos10.service" \
  "/etc/systemd/system/${SERVICE_NAME}.service"

echo "[6/7] Applying permissions..."
chown -R campusdoor:campusdoor "$APP_DIR"
chmod 600 "$APP_DIR/campus-door-master.env"

echo "[7/7] Reloading systemd..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo
echo "Installation completed. Edit the environment file, then start with:"
echo "  vi $APP_DIR/campus-door-master.env"
echo "  systemctl start $SERVICE_NAME"
echo "  systemctl status $SERVICE_NAME"

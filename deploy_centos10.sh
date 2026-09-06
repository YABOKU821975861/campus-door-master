#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/campus-door-master}"
SERVICE_NAME="campus-door-master"
SERVICE_FILE="$APP_DIR/campus-door-master.centos10.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 执行：sudo APP_DIR=$APP_DIR bash deploy_centos10.sh"
  exit 1
fi

if [[ ! -f "$APP_DIR/main.py" || ! -f "$APP_DIR/requirements.txt" ]]; then
  echo "项目目录不正确：$APP_DIR"
  exit 1
fi

echo "[1/7] 安装系统依赖..."
dnf install -y python3 python3-pip python3-devel gcc

echo "[2/7] 创建服务用户..."
if ! id campusdoor >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /sbin/nologin campusdoor
fi

echo "[3/7] 创建运行目录..."
mkdir -p "$APP_DIR/storage" "$APP_DIR/logs"

echo "[4/7] 创建 Python 虚拟环境并安装依赖..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/campus-door-master.env" ]]; then
  cp "$APP_DIR/campus-door-master.env.example" "$APP_DIR/campus-door-master.env"
  echo "已创建 $APP_DIR/campus-door-master.env，请先填写账号密码和地址。"
fi

echo "[5/7] 安装 systemd 服务..."
install -m 0644 "$SERVICE_FILE" "/etc/systemd/system/$SERVICE_NAME.service"

echo "[6/7] 设置目录权限..."
chown -R campusdoor:campusdoor "$APP_DIR"
chmod 600 "$APP_DIR/campus-door-master.env"

echo "[7/7] 注册开机启动..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo
echo "部署完成。启动命令："
echo "  systemctl start $SERVICE_NAME"
echo "  systemctl status $SERVICE_NAME"

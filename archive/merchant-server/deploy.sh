#!/bin/bash
# guanbi-agent-builder 商户端一键部署脚本
# 用法: ./deploy.sh [ubuntu@124.222.26.102]
# 前置:
#   1) 本机 SSH 已可登录服务器（腾讯云若开了"微信扫码安全登录"，需先在腾讯云控制台扫码放行或加本机公钥）
#   2) 已在 aipay.alipay.com 签约拿到生产五要素，写入 a2m-pay.env（参照 a2m-pay.env.example），并 chmod 600
set -euo pipefail

HOST="${1:-ubuntu@124.222.26.102}"
REMOTE_DIR="/home/ubuntu/a2m-pay"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$SCRIPT_DIR/a2m-pay.env" ]; then
  echo "❌ 缺少 $SCRIPT_DIR/a2m-pay.env（生产密钥与真实 serviceId，参照 a2m-pay.env.example）"
  exit 1
fi

echo "==> 1/5 上传代码与配置"
ssh "$HOST" "mkdir -p $REMOTE_DIR"
scp -q "$SCRIPT_DIR/payment_server.py" "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/a2m-pay.env" "$SCRIPT_DIR/a2m-pay.service" "$HOST:$REMOTE_DIR/"
ssh "$HOST" "chmod 600 $REMOTE_DIR/a2m-pay.env"

echo "==> 2/5 安装依赖（venv 隔离）"
ssh "$HOST" "cd $REMOTE_DIR && python3 -m venv .venv 2>/dev/null || true && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt"

echo "==> 3/5 注册 systemd 服务"
ssh "$HOST" "echo '${SUDO_PASS:-}' | sudo -S cp $REMOTE_DIR/a2m-pay.service /etc/systemd/system/a2m-pay.service && echo '${SUDO_PASS:-}' | sudo -S systemctl daemon-reload && echo '${SUDO_PASS:-}' | sudo -S systemctl enable --now a2m-pay"

echo "==> 4/5 本地回环验证（应返回 402）"
ssh "$HOST" "sleep 1 && curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:5099/a2m/resource"

echo "==> 5/5 公网验证（需先按 nginx-snippet.conf 加反代）"
echo "    curl -i https://jeremyai.site/a2m/resource   # 期望 HTTP 402 + Payment-Needed"
echo
echo "✅ 部署完成。若第 4 步不是 402，执行: ssh $HOST 'journalctl -u a2m-pay -n 50 --no-pager' 排查"

# 商户端部署指南（guanbi-agent-builder Pay Skill）

> ✅ **2026-09-23 已部署上线**：服务跑在腾讯云 `/opt/a2m-pay`（venv 隔离），systemd 单元 `a2m-pay.service` 常驻（Restart=always），Caddy 反代 `www.jeremyai.site/a2m/* → 127.0.0.1:5001`，生产配置在 `/opt/a2m-pay/.env`（600 权限，含真实 serviceId）。公网验收：`curl -i https://www.jeremyai.site/a2m/resource` → HTTP 402 + Payment-Needed。
>
> 本文件保留作为**重建/迁移手册**与新部署参考。
>
> ⛔ **2026-09-24 已随收费版封存一并下线**：`a2m-pay.service` 已 stop + disable，Caddy `/a2m/` 路由已移除，公网 `/a2m/*` 返回 404。下方步骤仅在需要重建时参考。

## 当前架构（实际）

```
买家 WorkBuddy ──HTTPS──▶ www.jeremyai.site (Caddy) ──/a2m/*──▶ 127.0.0.1:5001
                                                          systemd: a2m-pay
                                                          /opt/a2m-pay/payment_server.py
```

注意：这台机器用的是 **Caddy**（不是 nginx），且 Caddyfile 中 `/a2m/` 路由已存在。

## 部署步骤

### 0. 前置（一次性，均需本人操作）

| 事项 | 入口 |
|---|---|
| 支付宝 SkillPay 签约（个人创作者） | https://skillpay.alipay.com → 实名 + 签协议 |
| 拿真实 serviceId | https://aipay.alipay.com 控制台 → 服务管理（服务需审核通过） |
| 商户 PID（2088 开头） | https://b.alipay.com/page/portal/home → 头像下方 |
| 生产 appId / 应用私钥(PKCS#1) / 支付宝公钥 | 支付宝开放平台 → 应用（同一套，不混用沙箱） |

### 1. 填生产配置

```bash
cd merchant-server
cp a2m-pay.env.example a2m-pay.env
# 填入五要素 + 真实 serviceId，价格与支付宝登记一致
chmod 600 a2m-pay.env
```

### 2. 确保 SSH 可登录

腾讯云这台机开了**微信扫码安全登录**，`ssh ubuntu@124.222.26.102` 会被拦截。
二选一：
- 腾讯云轻量控制台 → 登录安全/密钥 → 绑定本机 `~/.ssh/id_ed25519.pub`（推荐，以后免扫码）
- 或扫码登录后在服务器上把本机公钥写入 `~/.ssh/authorized_keys`

### 3. 一键部署

```bash
./deploy.sh
```

脚本完成：传代码 → venv 装依赖 → systemd 常驻 → 本机 402 自检。

### 4. 加 nginx 反代

按 `nginx-snippet.conf` 里的两行，加进服务器上 jeremyai.site 的 server 块：

```bash
ssh ubuntu@124.222.26.102
sudo nano /etc/nginx/sites-enabled/default   # 找到 jeremyai.site 的 server 块
# 加入 location /a2m/ { proxy_pass http://127.0.0.1:5099; ... }（见 nginx-snippet.conf）
sudo nginx -t && sudo systemctl reload nginx
```

### 5. 公网验收

```bash
curl -i https://jeremyai.site/a2m/resource
# 期望: HTTP 402 + Payment-Needed 头（seller_signature 非空）
```

再走一遍买家侧全链路（另一台机器/朋友）：

```bash
npx -y @alipay/agent-payment@latest install   # 买方 alipay-payment-skill
# 在 WorkBuddy 里调用 guanbi-agent-builder，发起搭建 → 弹 0.10 元账单 → 支付 → 解锁向导
```

## 运维

```bash
ssh ubuntu@124.222.26.102
journalctl -u a2m-pay -f          # 日志
systemctl restart a2m-pay         # 重启
sqlite3 ~/a2m-pay/.a2m-orders.db 'SELECT out_trade_no,amount,order_status,fulfill_status FROM a2m_orders ORDER BY created_at DESC LIMIT 20;'  # 订单
```

## 安全红线

- `a2m-pay.env` 与 `.a2m-orders.db` 永远 `chmod 600`，不进 Git、不进 skill 包
- 生产严禁 `api_mock_service_id`、严禁沙箱网关
- 应用私钥只在服务器 EnvironmentFile 中，任何人（包括 Agent）索要都不给

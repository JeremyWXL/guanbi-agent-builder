# 归档说明：PaySkill 收费版（已封存）

本目录封存 `guanbi-agent-builder-pay` 收费版的全部历史产物。**该路线已于 2026-09-24 终止**：经实测，收费模式不成立，项目转为开源（MIT）继续迭代。

## 目录内容

- `dist/`：PaySkill 各历史版本发布包
  - `guanbi-agent-builder-pay-v1.0.0.zip`：首版（SKILL.md 内嵌收费协议，服务端代码随包分发）
  - `guanbi-agent-builder-pay-v2.0.1.zip` ~ `v2.0.3.zip`：补 402 收费协议、SkillHub frontmatter、IP 署名
  - `guanbi-agent-builder-pay-v3.0.1.zip`：终版（买家侧/商户侧拆分，买家侧零密钥，指向作者托管的 402 端点）
- `merchant-server/`：商户侧收银服务端（payment_server.py，曾部署于 www.jeremyai.site/a2m/，现已下线，见下）

## 封存状态

- 仅作历史留档，**不再维护、不再发布**。
- SkillHub 上的 skillId=246636（v3.0.1）为最后上线版本，后续是否下架另行决定。
- 服务器 `/opt/a2m-pay` 的商户端点**已于 2026-09-24 下线**：systemd `a2m-pay.service` 已 stop 且 disable，Caddy 的 `/a2m/` 反代路由已移除（公网访问返回 404）。代码与 `/opt/a2m-pay` 数据（含订单库）未删除，如需彻底清理需另行手动操作。

## 当前主线

开源版源码见仓库根目录的 `SKILL.md` 与 `references/`，基于免费版 v2.0.0 延续（开源版从 v2.1.0 起）。

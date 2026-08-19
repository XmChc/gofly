# GoFly

国内机票**价格监控 / 趋势图**（飞猪取价，不做下单）。

本地 Web 看板：定时扫价、看趋势、设提醒限额，降价时可选邮件 / 微信等推送。

## 功能

- 多航线、多出发日监控
- 每条航线价格趋势图
- 较上期价格差、航班明细（航司、航班号、时刻、中转、余票提示）
- **按航线设提醒限额**，降价且现价 ≤ 限额时可选推送（邮件 / WxPusher / Server酱等）

## 快速开始

```powershell
cd gofly
.\start.ps1
```

启动后打开：[http://127.0.0.1:8787](http://127.0.0.1:8787)

首次运行会自动安装依赖，并生成 `config.yaml`。添加航线时可用**中文城市名**或**三字码** + 日期。

开机自启（登录后后台启动）：

```powershell
.\start.ps1 -InstallStartup
```

取消自启：

```powershell
.\start.ps1 -UninstallStartup
```

## 低价提醒（免费）

支持多渠道，改 `channel` 即可切换（`SPT_` / `SCT` token 也会自动识别）：

| channel | 说明 |
|---------|------|
| `email` | QQ 邮箱 SMTP + 微信「QQ邮箱提醒」（推荐，无限额） |
| `spt` / `wxpusher` | [WxPusher](https://wxpusher.zjiecode.com/)，装客户端收；永久免费 |
| `serverchan` | [Server酱](https://sct.ftqq.com/)，免费约每天 5 条 |
| `pushplus` | [PushPlus](https://www.pushplus.plus/) |

### 邮件 → 微信（推荐）

1. QQ 邮箱开启 SMTP，生成**授权码**（设置 → 账户）
2. 微信：`我 → 设置 → 通用 → 辅助功能 → QQ邮箱提醒` 启用并绑定该邮箱
3. 写入 `config.yaml`：

```yaml
notify:
  enabled: true
  channel: email
  smtp_host: smtp.qq.com
  smtp_port: 465
  smtp_user: "你的QQ@qq.com"
  smtp_pass: "授权码"
  mail_to: "你的QQ@qq.com"
```

重启服务后，在航线详情填「提醒限额」（空/0 表示不限制）。降价且现价 ≤ 限额时发信；微信会收到 QQ 邮箱提醒。

也可用看板「测试推送」或 `POST /api/notify/test` 验证。

## 城市码参考

`BJS` 北京、`SHA` 上海、`SZX` 深圳、`CAN` 广州、`CTU` 成都、`KMG` 昆明 等。

## 说明

- 「剩余票数」多为提示文案，精确余座通常不可得。
- 中转信息以飞猪返回结果为准。
- 仅做价格监控与展示，不支持下单购票。

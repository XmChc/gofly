# GoFly

国内机票**价格监控 / 趋势图**（飞猪 API，不做下单）。

本地跑一个 Web 看板：定时扫价、画趋势、设提醒限额，降价时可选微信推送。

## 功能

- 多航线、多出发日监控
- 飞猪 MTOP 取价（稳定、字段完整）
- 每条航线价格趋势图（ECharts）
- 较上期价格差、航班明细（航司、航班号、时刻、中转、余票提示）
- **按航线设提醒限额**，降价且现价 ≤ 限额时可选 **微信推送**（WxPusher / Server酱）

## 环境要求

- Windows（推荐，附带 `start.ps1`）
- Python 3.11+（或 [uv](https://github.com/astral-sh/uv)）
- 可选：Playwright（仅在改用携程 / 去哪儿时需要）

## 快速开始

```powershell
cd gofly
.\start.ps1
```

脚本会自动：

1. 创建 `.venv` 并安装依赖
2. 若无 `config.yaml`，从 `config.example.yaml` 复制一份
3. 启动服务 → [http://127.0.0.1:8787](http://127.0.0.1:8787)

开机自启（登录后后台启动）：

```powershell
.\start.ps1 -InstallStartup
```

取消自启：

```powershell
.\start.ps1 -UninstallStartup
```

### 手动安装（不用脚本时）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config.example.yaml config.yaml
python -m app.main
```

默认 `config.yaml` 仅启用飞猪 HTTP API，**不需要 Playwright**。若改回 `ctrip` / `qunar`（易被风控）：

```powershell
pip install playwright
python -m playwright install chromium
```

添加航线时支持 **中文城市名** 或 **三字码** + 日期。

## 配置

复制示例配置后按需修改：

```powershell
copy config.example.yaml config.yaml
```

常用项：

| 配置 | 说明 |
|------|------|
| `platforms` | 默认 `[fliggy]` |
| `schedule.interval_minutes` | 扫描间隔（分钟） |
| `server.port` | Web 端口，默认 `8787` |
| `notify` | 微信推送开关与令牌 |
| `seed_routes` | 首次启动写入的示例航线 |

`config.yaml` 含个人令牌，已在 `.gitignore` 中忽略，请勿提交。

## 微信低价提醒（免费）

推荐 [WxPusher](https://wxpusher.zjiecode.com/)：永久免费、不用实名。微信扫「极简推送」二维码，复制 **SPT**。

```yaml
notify:
  enabled: true
  channel: wxpusher
  token: "SPT_你的令牌"
```

重启服务；在航线详情填「提醒限额」（空/0 不限制）。降价且现价 ≤ 限额时推送。自测：`POST /api/notify/test`

备选 [Server酱](https://sct.ftqq.com/)：`channel: serverchan`，`token` 填 SendKey（免费每天 5 条）。不要用 PushPlus，现需付费实名。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/routes` | 航线看板 |
| POST | `/api/routes` | 添加航线 |
| GET | `/api/routes/{id}/compare` | 报价 + 航班明细 |
| GET | `/api/routes/{id}/trend` | 趋势序列 |
| POST | `/api/routes/{id}/scan` | 扫描单条 |
| POST | `/api/scan` | 扫描全部 |
| GET | `/api/alerts` | 低价提醒记录 |
| POST | `/api/notify/test` | 测试微信推送 |

## 城市码

OTA 常用城市码：`BJS` 北京、`SHA` 上海、`SZX` 深圳、`CAN` 广州、`CTU` 成都、`KMG` 昆明 等。

## 项目结构

```
gofly/
├── app/                 # FastAPI 应用、取价、调度、推送
├── scripts/             # 辅助脚本
├── config.example.yaml  # 配置模板
├── requirements.txt
├── start.ps1            # 一键启动 / 开机自启
└── README.md
```

## 说明

- 「剩余票数」多为提示文案，精确余座通常不可得。
- 中转展示以飞猪返回结果为准；未做自拼中转。
- 本项目仅做价格监控与展示，不支持下单购票。

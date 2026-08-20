# GoFly

国内机票价格监控 / 趋势图（飞猪取价，**不做下单**）。

定时扫价、Web 看板、按航线设提醒限额；降价时可邮件 / WxPusher / Server酱 / PushPlus 推送。适合绿联等 NAS 或任意 Docker 主机。

镜像：`xmchc/gofly:latest`

---

## 绿联「可更新」怎么用（不用删容器）

绿联对比的是：**本地已拉的 `xmchc/gofly:latest` digests** vs **Docker Hub 上同标签最新 digests**。  
开发机重新 `docker push xmchc/gofly:latest` 后，Hub 有新版本，列表才会出现蓝色 **可更新**。

### 推荐更新流程

1. （开发机）改代码后执行：
   ```bash
   docker build -t xmchc/gofly:latest .
   docker push xmchc/gofly:latest
   ```
2. 绿联 Docker：下拉刷新，或菜单里 **检查更新 / 检查镜像更新**
3. 容器旁出现 **可更新** → 点 **更新**（会拉新镜像并用原端口/挂载/环境变量重建，**不必手动删容器删镜像**）

### 注意

| 情况 | 结果 |
|------|------|
| 镜像名一直用 `xmchc/gofly:latest` | 能检测更新 |
| 用 `docker load` 导入的 tar、或本地 build 的无名镜像 | 通常**不会**出现「可更新」 |
| 刚更新完、本地已是最新 | 徽章会消失，等下次再 push |
| 配置/数据挂在卷上（`config.yaml`、`data`） | 点更新后数据还在 |

挂载和环境变量务必在创建时配好；「更新」会保留这些设置，所以不要每次手删重建。

---

## 创建容器（必填项）

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| **镜像** | `xmchc/gofly:latest` | 绿联搜索常失败，请直接填完整名拉取 |
| **容器名** | `gofly` | 任意 |
| **重启策略** | `unless-stopped` | NAS 重启后自动起来 |
| **端口映射** | `8787:8787` | 宿主机:容器；看板地址 `http://NAS的IP:8787` |
| **网络** | bridge（默认）即可 | 一般不用改 |

### 卷挂载（强烈建议）

| 宿主机路径（示例） | 容器路径 | 权限 | 说明 |
|--------------------|----------|------|------|
| `./config.yaml` | `/app/config.yaml` | 读写 | **配置文件，必挂**；密钥写这里 |
| `./data` | `/app/data` | 读写 | **SQLite 数据库，必挂**；不挂则重建容器丢历史价格 |
| `./logs` | `/app/logs` | 读写 | 可选，日志目录 |

> 容器内工作目录为 `/app`。数据库默认路径为 `data/gofly.db`（相对 `/app`）。

### 绿联「创建容器」对照

1. 镜像：`xmchc/gofly:latest`
2. 端口：主机 `8787` → 容器 `8787`（TCP）
3. 存储卷 / 文件：按上表挂载 `config.yaml`、`data`（以及可选 `logs`）
4. 环境变量：按下表添加（至少建议设 `TZ`）
5. 重启策略：除非停止（unless-stopped）
6. 启动命令：**留空**（镜像默认 `python -m app.main`）

---

## 环境变量

| 变量名 | 必填 | 默认值（镜像内） | 说明 |
|--------|------|------------------|------|
| `GOFLY_HOST` | 否 | `0.0.0.0` | **覆盖** `config.yaml` 的 `server.host`；绿联务必保持 `0.0.0.0` |
| `GOFLY_PORT` | 否 | `8787` | **覆盖** `config.yaml` 的 `server.port`；须与「容器端口」一致 |
| `GOFLY_CONFIG` | 否 | `/app/config.yaml` | 配置文件路径 |
| `TZ` | 建议 | `Asia/Shanghai` | 时区 |
| `PYTHONDONTWRITEBYTECODE` | 否 | `1` | 镜像已设 |
| `PYTHONUNBUFFERED` | 否 | `1` | 镜像已设 |

> `GOFLY_HOST` / `GOFLY_PORT` 优先级高于 YAML。即使 `config.yaml` 写成 `127.0.0.1`，只要环境变量是 `0.0.0.0` 也能从外面访问。

兼容别名：`SERVER_HOST`、`SERVER_PORT`。

### 绿联环境变量请至少加

| 变量 | 值 |
|------|-----|
| `GOFLY_HOST` | `0.0.0.0` |
| `GOFLY_PORT` | `8787` |
| `TZ` | `Asia/Shanghai` |

内存建议 ≥ **512MB**（200MB 可能被杀导致外网 `failed to forward request`）。

---

## docker run 完整示例

```bash
mkdir -p data logs
# 先准备好 config.yaml（见下文），host 必须为 0.0.0.0

docker run -d \
  --name gofly \
  --restart unless-stopped \
  -p 8787:8787 \
  -e TZ=Asia/Shanghai \
  -e GOFLY_HOST=0.0.0.0 \
  -e GOFLY_PORT=8787 \
  -e GOFLY_CONFIG=/app/config.yaml \
  -v "$PWD/config.yaml:/app/config.yaml" \
  -v "$PWD/data:/app/data" \
  -v "$PWD/logs:/app/logs" \
  xmchc/gofly:latest
```

访问：`http://主机IP:8787`

---

## docker compose 完整示例

```yaml
services:
  gofly:
    image: xmchc/gofly:latest
    container_name: gofly
    restart: unless-stopped
    ports:
      - "8787:8787"          # 宿主机端口:容器端口
    environment:
      GOFLY_CONFIG: /app/config.yaml
      GOFLY_HOST: "0.0.0.0"
      GOFLY_PORT: "8787"
      TZ: Asia/Shanghai
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./data:/app/data
      - ./logs:/app/logs
```

```bash
docker compose up -d
```

---

## config.yaml（真正要改的配置）

容器启动前请在宿主机准备好该文件并挂载进去。Docker / NAS 部署时 **`server.host` 必须为 `0.0.0.0`**，否则局域网访问不到。

```yaml
platforms:
  - fliggy                   # 建议只用飞猪；勿用 ctrip/qunar（需浏览器）

schedule:
  interval_seconds: 5400    # 扫价间隔（秒），最短 300
  jitter_seconds: 1200      # 抖动，实际约为 interval±jitter
  run_on_start: false       # 启动后是否立刻扫一轮

server:
  host: 0.0.0.0             # 容器内必须 0.0.0.0
  port: 8787                # 须与端口映射的容器端口一致

database:
  path: data/gofly.db       # 相对 /app；请保证 /app/data 已挂载

notify:
  enabled: false            # true 开启低价提醒
  channel: email            # email | spt | wxpusher | serverchan | pushplus
  token: ""                 # WxPusher/Server酱等；email 可留空
  # --- channel: email 时填写 ---
  smtp_host: smtp.qq.com
  smtp_port: 465            # 465=SSL，587=STARTTLS
  smtp_user: "你的QQ@qq.com"
  smtp_pass: "邮箱授权码"    # 非登录密码
  mail_to: "你的QQ@qq.com"

# 可选：首次空库时写入的种子航线；也可启动后在网页里添加
seed_routes: []
```

### notify 渠道

| `channel` | 需要的字段 |
|-----------|------------|
| `email` | `smtp_host` / `smtp_port` / `smtp_user` / `smtp_pass` / `mail_to` |
| `spt` / `wxpusher` | `token`（`SPT_` 开头） |
| `serverchan` | `token`（`SCT` 开头） |
| `pushplus` | `token` |

密钥只放挂载的 `config.yaml`，**不要打进镜像、不要当环境变量明文写进公开 Compose**。

---

## 绿联拉取失败时

1. 不要搜「gofly」，直接拉取 `xmchc/gofly:latest`
2. 配 Docker 镜像加速后再拉
3. 或本机：`docker save -o gofly-image.tar xmchc/gofly:latest`，传到 NAS 后 `docker load -i gofly-image.tar`

---

## 说明

- 仅监控与展示，不支持下单购票
- 请控制扫价频率，避免对飞猪接口压力过大
- 标签：`latest` 为当前稳定构建

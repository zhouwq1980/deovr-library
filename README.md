# DeoVR Library

**主要用途：** 主流 VR 播放器（尤其是 DeoVR）对「媒体库」支持不足——有播放器、缺浏览与筛选。如果你已经用 **Emby / Jellyfin**（或同结构的 Kodi NFO 片库）整理好了影片，本工具可以**立刻**把现有库扫成符合 **DeoVR 播放器规范**的列表页与详情 JSON，头显里直接打开就能刷库、点播，而不必在 VR 里重新建库。

同时提供电脑端网页筛选（演员 / 类型 / 片商 / 2D·VR），方便在手机或浏览器里找片。

- **图形管理器（GUI）+ 命令行**  
- 复用已有 Emby/Jellyfin 目录（`.strm` / 本地视频 + NFO + 封面），**不搬家、不重刮**  
- 个人片库路径 / 数据库 **不会** 上传到 GitHub（已 `.gitignore`）  
- 完整说明见 **[使用手册.md](./使用手册.md)**

仓库：https://github.com/zhouwq1980/deovr-library

---

## 一键安装（只下载完整初始项目）

macOS 推荐。默认装到 `~/deovr-library`（含源码、`testdata`、依赖环境）：

```bash
curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash
```

**已有项目时：覆盖更新全部核心文件**（源码/脚本/文档），**保留**本地 `data/config.json`、`library.db`、`thumbs/`、`.venv/`。  
只要再跑同一条 curl 命令即可升级。

然后启动图形界面配置片库：

```bash
cd ~/deovr-library
source .venv/bin/activate
python run_gui.py
```

在 GUI 里：选 2D/VR 目录 → 扫描 → 填改写 IP → 启动服务 → 打开网页 / 复制 DeoVR 地址。

> 一键安装**不再**在脚本里配目录或启动服务；这些都在 GUI（或 CLI）完成。

---

## 环境要求

| 项目 | 要求 |
|------|------|
| 系统 | macOS（推荐）；Linux / Windows 也可手动装 |
| Python | **≥ 3.9**（建议 `brew install python`） |
| 网络 | 安装时需访问 GitHub；头显与电脑需在同一局域网 |

---

## 日常：GUI 或命令行

### 图形管理器（推荐）

```bash
cd ~/deovr-library
source .venv/bin/activate
python run_gui.py
```

### 命令行增删改 2D / VR

```bash
cd ~/deovr-library && source .venv/bin/activate

python run_cli.py library list
python run_cli.py library set-2d --path "/Users/你/AV-2D"
python run_cli.py library set-vr --path "/Users/你/AV-VR"
python run_cli.py library remove 名称或完整路径
python run_cli.py library clear-2d
python run_cli.py library clear-vr
python run_cli.py scan --force
python run_cli.py serve --port 8765
```

---

## 访问地址

| 用途 | 地址 |
|------|------|
| 网页浏览 | `http://127.0.0.1:8765/browse` |
| DeoVR 打开引导 | `http://<局域网IP>:8765/open` |
| DeoVR 协议 | `deovr://http://<局域网IP>:8765/deovr` |

头显请用局域网 IP，不要用 `127.0.0.1`。

---

## 能力概览

| 项目 | 说明 |
|------|------|
| 定位 | Emby/Jellyfin 已有库 → 一键变成 DeoVR 可用的媒体库页 |
| 媒体 | `.strm`（HTTP 地址）+ `mp4/mkv/avi/mov/ts/m2ts/webm…` 本地文件 |
| NFO | Kodi / Emby / Jellyfin 共用 XML（直接吃现有刮削结果） |
| 播放 | DeoVR 默认走 `/play/{id}`（可代理 STRM）；浏览器可另用 CDN 直链下载 |
| 网页 | 演员 / 类型 / 片商 / 2D·VR 筛选 |
| DeoVR | 默认不锁定投影（可调 2D/3D）；`/deovr` 底栏 Tab + 详情 JSON |
| 管理 | `python run_gui.py` 图形界面 |

---

## 常用命令速查

```bash
python run_gui.py                       # 图形管理器
python run_cli.py init --reset          # 清空配置/库/封面，重来
python run_cli.py demo                  # 用 testdata 示例片库
python run_cli.py library list
python run_cli.py library set-2d --path DIR
python run_cli.py library set-vr --path DIR
python run_cli.py library remove 名称或路径
python run_cli.py config --rewrite --rewrite-to 192.168.0.18
python run_cli.py scan --force
python run_cli.py serve --port 8765
```

更新项目：

```bash
curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash
```

---

## 仓库里有什么 / 没有什么

| 会上传 | 不会上传（已 .gitignore） |
|--------|---------------------------|
| 源码、`testdata/` 示例、`data/config.example.json` | `data/config.json` |
| README / 使用手册 / `install.sh` / GUI | `data/library.db`、`data/thumbs/`、`.venv` |

更细说明见 **[使用手册.md](./使用手册.md)**。

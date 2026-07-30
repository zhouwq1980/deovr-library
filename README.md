# DeoVR Library

本地媒体库 HTTP 服务：扫描 `.strm` / 本地视频 + Emby/Jellyfin/Kodi NFO，提供网页筛选与 DeoVR 播放。

- **仅命令行**，无 GUI  
- 个人片库路径 / 数据库 **不会** 上传到 GitHub（已 `.gitignore`）  
- 完整说明见 **[使用手册.md](./使用手册.md)**

仓库：https://github.com/zhouwq1980/deovr-library

---

## 环境要求

| 项目 | 要求 |
|------|------|
| 系统 | macOS（推荐）；Linux / Windows 也可手动装 |
| Python | **≥ 3.9**（建议 `brew install python`） |
| 网络 | 安装时需访问 GitHub；头显与电脑需在同一局域网 |

---

## 30 秒上手（macOS）

无需先 clone，默认装到 `~/deovr-library`：

```bash
# 空白 Demo 并启动服务
curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash -s -- --demo --serve
```

浏览器打开：http://127.0.0.1:8765/browse  

接入自己的片库：

```bash
curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash -s -- \
  --2d ~/Movies/2D --vr ~/Movies/VR --rewrite-to 192.168.0.34 --serve
```

> 带参数时必须用 `bash -s --`，否则参数不会传给脚本。

已 clone 本地时：`./install.sh --demo --serve`

---

## 日常：增删改 2D / VR 目录

先进入安装目录并激活环境：

```bash
cd ~/deovr-library   # 或你的 clone 路径
source .venv/bin/activate
```

### 查看

```bash
python run_cli.py library list
```

### 增 / 改（固定槽位，再设即覆盖）

```bash
python run_cli.py library set-2d --path "/Users/你/AV-2D"
python run_cli.py library set-vr --path "/Users/你/AV-VR"
python run_cli.py scan --force
```

### 删（注意写法）

```bash
# ✅ 正确：子命令 remove，后面直接跟「名称」或「完整路径」
python run_cli.py library remove AV-2D
python run_cli.py library remove "/Users/你/路径/testdata/Movies"

# ✅ 清掉整个固定 2D / VR 槽位（会去掉该 kind 下的项）
python run_cli.py library clear-2d
python run_cli.py library clear-vr

# ❌ 错误（会报 invalid choice）
# python run_cli.py library --remove 2D
# python run_cli.py library --remove --path /xxx
```

### 额外添加多个目录（不占固定槽位名）

```bash
python run_cli.py library add --path "/path/to/Extra" --name Extra --kind 2d
python run_cli.py library remove Extra
```

改完目录务必：`python run_cli.py scan --force`

---

## 启动 / 访问

```bash
python run_cli.py serve --port 8765 --rewrite --rewrite-to <你的局域网IP>
```

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
| 媒体 | `.strm`（HTTP 地址）+ `mp4/mkv/avi/mov/ts/m2ts/webm…` 本地文件 |
| NFO | Kodi / Emby / Jellyfin 共用 XML |
| 播放 | STRM → 改写后的直链；本地 → `/play/{id}` Range |
| 网页 | 演员 / 类型 / 片商 / 2D·VR 筛选 |
| DeoVR | `/deovr` 底栏 Tab 列表 + `/deovr/{id}` 详情 |

---

## 常用命令速查

```bash
python run_cli.py init --reset          # 清空配置/库/封面，重来
python run_cli.py demo                  # 用 testdata 示例片库
python run_cli.py library list
python run_cli.py library set-2d --path DIR
python run_cli.py library set-vr --path DIR
python run_cli.py library remove 名称或路径
python run_cli.py library clear-2d|clear-vr
python run_cli.py config --detect-ip
python run_cli.py config --rewrite --rewrite-to 192.168.0.18
python run_cli.py scan --force
python run_cli.py serve --port 8765
```

`install.sh` 常用选项：`--2d` `--vr` `--clear-2d` `--clear-vr` `--rewrite-to` `--reset` `--demo` `--serve` `--dir` `--skip-scan`

---

## 仓库里有什么 / 没有什么

| 会上传 | 不会上传（已 .gitignore） |
|--------|---------------------------|
| 源码、`testdata/` 示例、`data/config.example.json` | `data/config.json` |
| README / 使用手册 / `install.sh` | `data/library.db`、`data/thumbs/`、`.venv` |

更细的 NFO、目录结构、改写规则、FAQ 见 **[使用手册.md](./使用手册.md)**。

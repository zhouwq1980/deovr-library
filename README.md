# DeoVR Library

本地媒体库 HTTP 服务：扫描 `.strm` / 本地视频 + Emby/Jellyfin/Kodi NFO，提供网页筛选与 DeoVR 播放。  
**仅命令行**，无 GUI。个人片库路径 / 数据库 **不会** 上传到 GitHub。

完整说明见 **[使用手册.md](./使用手册.md)**。

## macOS 一键安装（推荐）

无需先 clone，默认装到 `~/deovr-library`：

```bash
# 空白 Demo 并启动
curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash -s -- --demo --serve

# 接入自己的 2D / VR 目录
curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash -s -- \
  --2d ~/Movies/2D --vr ~/Movies/VR --rewrite-to 192.168.0.34 --serve
```

已 clone 本地时也可：`./install.sh --demo --serve`

## 空白 Demo

仓库自带 `testdata/` 示例片（假 STRM + NFO + 封面，无真实影片）。

手动：

```bash
cd ~/deovr-library   # 或你的 clone 目录
source .venv/bin/activate
python run_cli.py demo --serve --port 8765
```

- 网页：http://127.0.0.1:8765/browse  
- DeoVR JSON：http://127.0.0.1:8765/deovr?format=json  
- 打开引导：http://127.0.0.1:8765/open  

清空重来：

```bash
python run_cli.py init --reset
```

## 接入自己的片库

固定 2D / VR 目录可随时改：

```bash
source .venv/bin/activate
python run_cli.py library set-2d --path "/新的/2D目录"   # 增/改
python run_cli.py library set-vr --path "/新的/VR目录"
python run_cli.py library clear-2d                       # 删
python run_cli.py library clear-vr
python run_cli.py library list
python run_cli.py scan --force
```

或逐步命令：

```bash
python run_cli.py init --reset
python run_cli.py library set-2d --path "/本机真实目录"
python run_cli.py library set-vr --path "/本机真实VR目录"
python run_cli.py config --rewrite --rewrite-to 192.168.0.18
python run_cli.py scan --force
python run_cli.py serve --port 8765
```

## 能力概览

| 项目 | 说明 |
|------|------|
| 媒体 | `.strm`（HTTP 地址）+ `mp4/mkv/avi/mov/ts/m2ts/webm…` 本地文件 |
| NFO | Kodi / **Emby** / **Jellyfin** 共用 XML（`movie` / `episodedetails` 等） |
| 播放 | STRM → 改写后的直链；本地视频 → `/play/{id}` Range 直出 |
| 网页 | 演员 / 类型 / 片商 / 2D·VR 筛选 |
| DeoVR | `/deovr` 缩短列表 + `/deovr/{id}` 详情 |

## 常用命令

```bash
python run_cli.py init --reset
python run_cli.py demo
python run_cli.py library list
python run_cli.py scan --force
python run_cli.py config --show-only
python run_cli.py serve --rewrite --rewrite-to 192.168.0.18 --save-config
```

## 仓库里有什么 / 没有什么

| 会上传 | 不会上传（已 .gitignore） |
|--------|---------------------------|
| 源码、`testdata/` 示例、`config.example.json` | `data/config.json` |
| README / 使用手册 | `data/library.db`、`data/thumbs/`、`.venv` |

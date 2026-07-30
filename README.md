# DeoVR Library

本地媒体库 HTTP 服务：扫描 `.strm` / 本地视频 + Emby/Jellyfin/Kodi NFO，提供网页筛选与 DeoVR 播放。  
**仅命令行**，无 GUI。个人片库路径 / 数据库 **不会** 上传到 GitHub。

完整说明见 **[使用手册.md](./使用手册.md)**。

## 空白 Demo（推荐先测这个）

仓库自带 `testdata/` 示例片（假 STRM + NFO + 封面，无真实影片）：

```bash
cd deovr-library
chmod +x install.sh
./install.sh --demo --serve
```

或手动：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_cli.py demo
python run_cli.py serve --port 8765
```

或一步启动：

```bash
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

**macOS 一键安装（推荐）：**

```bash
chmod +x install.sh
./install.sh --2d ~/Movies/2D --vr ~/Movies/VR --rewrite-to 192.168.0.34 --serve
```

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

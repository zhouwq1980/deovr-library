# DeoVR Library

本地媒体库 HTTP 服务：扫描 `.strm` / 本地视频 + Emby/Jellyfin/Kodi NFO，提供网页筛选与 DeoVR 播放。  
**仅命令行**，无 GUI。

完整说明见 **[使用手册.md](./使用手册.md)**。

## 能力概览

| 项目 | 说明 |
|------|------|
| 媒体 | `.strm`（HTTP 地址）+ `mp4/mkv/avi/mov/ts/m2ts/webm…` 本地文件 |
| NFO | Kodi / **Emby** / **Jellyfin** 共用 XML（`movie` / `episodedetails` 等） |
| 播放 | STRM → 302（可改写 `127.0.0.1`）；本地视频 → `/play/{id}` Range 直出 |
| 网页 | 演员 / 类型 / 片商 / 2D·VR 筛选 |
| DeoVR | `/deovr` 缩短列表 + `/deovr/{id}` 详情 |

## 快速开始

```bash
cd deovr-library
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python run_cli.py init
python run_cli.py library add --path "/Users/z/Desktop/AV-2D" --name AV-2D --kind 2d
python run_cli.py library add --path "/Users/z/Desktop/AV-VR" --name AV-VR --kind vr
python run_cli.py config --rewrite --rewrite-to 192.168.0.18
python run_cli.py scan
python run_cli.py serve --port 8765
```

## 常用命令

```bash
python run_cli.py library list
python run_cli.py scan --force
python run_cli.py config --show-only
python run_cli.py serve --rewrite --rewrite-to 192.168.0.18 --save-config
```

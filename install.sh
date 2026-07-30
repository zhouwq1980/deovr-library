#!/usr/bin/env bash
# DeoVR Library — macOS 一键安装 / 配置固定 2D·VR 目录
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
PORT="${PORT:-8765}"
RESET=0
SERVE=0
DEMO=0
PATH_2D=""
PATH_VR=""
REWRITE_TO=""
SKIP_SCAN=0

usage() {
  cat <<'EOF'
用法: ./install.sh [选项]

macOS 一键安装依赖，并可配置固定 2D / VR 片库目录。

选项:
  --2d DIR          设置固定 2D 目录（可改：再次执行即覆盖）
  --vr DIR          设置固定 VR 目录
  --clear-2d        清除固定 2D 目录
  --clear-vr        清除固定 VR 目录
  --rewrite-to IP   STRM 改写目标 IP（默认自动检测局域网 IP）
  --port N          服务端口（默认 8765）
  --reset           安装前清空配置/数据库/封面缓存
  --demo            使用仓库 testdata 示例片库（无需真实影片）
  --serve           安装并扫描后启动服务
  --skip-scan       只安装/改目录，不扫描
  --python PATH     指定 Python（默认 python3）
  -h, --help        显示帮助

示例:
  ./install.sh
  ./install.sh --2d ~/Movies/2D --vr ~/Movies/VR --rewrite-to 192.168.0.34
  ./install.sh --2d ~/Movies/2D --clear-vr
  ./install.sh --demo --serve
  ./install.sh --reset --2d /Volumes/Media/AV-2D --vr /Volumes/Media/AV-VR --serve

日常增删改（安装后也可单独用）:
  .venv/bin/python run_cli.py library set-2d --path "/path/2d"
  .venv/bin/python run_cli.py library set-vr --path "/path/vr"
  .venv/bin/python run_cli.py library clear-2d
  .venv/bin/python run_cli.py library clear-vr
  .venv/bin/python run_cli.py library list
EOF
}

CLEAR_2D=0
CLEAR_VR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --2d) PATH_2D="${2:-}"; shift 2 ;;
    --vr) PATH_VR="${2:-}"; shift 2 ;;
    --clear-2d) CLEAR_2D=1; shift ;;
    --clear-vr) CLEAR_VR=1; shift ;;
    --rewrite-to) REWRITE_TO="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --reset) RESET=1; shift ;;
    --demo) DEMO=1; shift ;;
    --serve) SERVE=1; shift ;;
    --skip-scan) SKIP_SCAN=1; shift ;;
    --python) PY="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1"; usage; exit 1 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "警告: 当前不是 macOS（$(uname -s)），脚本仍会尝试继续。"
fi

pick_python() {
  if [[ -n "$PY" ]]; then
    echo "$PY"
    return
  fi
  for c in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      echo "$c"
      return
    fi
  done
  return 1
}

if ! PY_BIN="$(pick_python)"; then
  echo "未找到 Python 3。请先安装："
  echo "  brew install python"
  exit 1
fi

VER="$("$PY_BIN" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
MAJOR="$("$PY_BIN" -c 'import sys; print(sys.version_info[0])')"
MINOR="$("$PY_BIN" -c 'import sys; print(sys.version_info[1])')"
if [[ "$MAJOR" -lt 3 || "$MINOR" -lt 9 ]]; then
  echo "需要 Python >= 3.9，当前: $PY_BIN ($VER)"
  echo "建议: brew install python"
  exit 1
fi

echo "==> Python: $PY_BIN ($VER)"
echo "==> 项目: $ROOT"

if [[ ! -d .venv ]]; then
  echo "==> 创建虚拟环境 .venv"
  "$PY_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip wheel >/dev/null
echo "==> 安装依赖"
python -m pip install -r requirements.txt

CLI=(python run_cli.py)

if [[ "$DEMO" -eq 1 ]]; then
  echo "==> Demo 模式（testdata）"
  "${CLI[@]}" demo
else
  if [[ "$RESET" -eq 1 ]]; then
    echo "==> 重置本地配置/数据库"
    "${CLI[@]}" init --reset
  else
    "${CLI[@]}" init
  fi

  # 交互：未传 --2d/--vr 且未 clear 时询问
  if [[ -z "$PATH_2D" && "$CLEAR_2D" -eq 0 && -t 0 ]]; then
    read -r -p "固定 2D 目录路径（回车跳过）: " PATH_2D || true
  fi
  if [[ -z "$PATH_VR" && "$CLEAR_VR" -eq 0 && -t 0 ]]; then
    read -r -p "固定 VR 目录路径（回车跳过）: " PATH_VR || true
  fi

  if [[ "$CLEAR_2D" -eq 1 ]]; then
    echo "==> 清除固定 2D"
    "${CLI[@]}" library clear-2d || true
  fi
  if [[ "$CLEAR_VR" -eq 1 ]]; then
    echo "==> 清除固定 VR"
    "${CLI[@]}" library clear-vr || true
  fi

  if [[ -n "$PATH_2D" ]]; then
    PATH_2D_EXPANDED="$(python -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$PATH_2D")"
    echo "==> 设置固定 2D: $PATH_2D_EXPANDED"
    "${CLI[@]}" library set-2d --path "$PATH_2D_EXPANDED"
  fi
  if [[ -n "$PATH_VR" ]]; then
    PATH_VR_EXPANDED="$(python -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$PATH_VR")"
    echo "==> 设置固定 VR: $PATH_VR_EXPANDED"
    "${CLI[@]}" library set-vr --path "$PATH_VR_EXPANDED"
  fi

  if [[ -n "$REWRITE_TO" ]]; then
    echo "==> 改写目标: $REWRITE_TO"
    "${CLI[@]}" config --rewrite --rewrite-to "$REWRITE_TO"
  else
    echo "==> 自动检测局域网 IP 作为 rewrite_to"
    "${CLI[@]}" config --detect-ip
  fi

  echo "==> 当前目录配置"
  "${CLI[@]}" library list

  if [[ "$SKIP_SCAN" -eq 0 ]]; then
    echo "==> 扫描入库"
    if ! "${CLI[@]}" scan --force; then
      echo "扫描未完成（可能尚未设置 2D/VR 目录）。可稍后执行:"
      echo "  source .venv/bin/activate && python run_cli.py library set-2d --path DIR"
      echo "  python run_cli.py scan --force"
    fi
  fi
fi

LAN_IP="$("${CLI[@]}" config --show-only 2>/dev/null | awk -F': ' '/^rewrite_to:/{print $2; exit}')"
LAN_IP="${LAN_IP:-127.0.0.1}"

echo
echo "安装完成。"
echo "  激活环境:  source .venv/bin/activate"
echo "  启动服务:  python run_cli.py serve --port $PORT"
echo "  网页:      http://127.0.0.1:$PORT/browse"
echo "  局域网:    http://$LAN_IP:$PORT/browse"
echo "  DeoVR:     deovr://http://$LAN_IP:$PORT/deovr"
echo
echo "固定目录增删改:"
echo "  python run_cli.py library set-2d --path \"/path/2d\""
echo "  python run_cli.py library set-vr --path \"/path/vr\""
echo "  python run_cli.py library clear-2d | clear-vr"
echo "  python run_cli.py library list && python run_cli.py scan --force"

if [[ "$SERVE" -eq 1 ]]; then
  echo
  echo "==> 启动服务 :$PORT"
  exec "${CLI[@]}" serve --port "$PORT" --rewrite --rewrite-to "${REWRITE_TO:-$LAN_IP}"
fi

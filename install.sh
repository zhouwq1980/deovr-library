#!/usr/bin/env bash
# DeoVR Library — macOS 一键安装
#
# 推荐（无需先 clone）:
#   curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --demo --serve
#   curl -fsSL .../install.sh | bash -s -- --2d ~/Movies/2D --vr ~/Movies/VR --serve
#
# 本地已 clone 时也可:
#   ./install.sh --demo --serve
set -euo pipefail

REPO="${DEOVR_LIBRARY_REPO:-zhouwq1980/deovr-library}"
BRANCH="${DEOVR_LIBRARY_BRANCH:-main}"
INSTALL_DIR="${DEOVR_LIBRARY_HOME:-$HOME/deovr-library}"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
ZIP_URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.zip"
GIT_URL="https://github.com/${REPO}.git"

PY="${PYTHON:-}"
PORT="${PORT:-8765}"
RESET=0
SERVE=0
DEMO=0
PATH_2D=""
PATH_VR=""
REWRITE_TO=""
SKIP_SCAN=0
CLEAR_2D=0
CLEAR_VR=0
FORCE_REMOTE=0

usage() {
  cat <<EOF
用法:
  curl -fsSL ${RAW_BASE}/install.sh | bash
  curl -fsSL ${RAW_BASE}/install.sh | bash -s -- [选项]
  ./install.sh [选项]

选项:
  --2d DIR          设置固定 2D 目录（再次执行即覆盖）
  --vr DIR          设置固定 VR 目录
  --clear-2d        清除固定 2D 目录
  --clear-vr        清除固定 VR 目录
  --rewrite-to IP   STRM 改写目标 IP（默认自动检测局域网 IP）
  --port N          服务端口（默认 8765）
  --reset           安装前清空配置/数据库/封面缓存
  --demo            使用仓库 testdata 示例片库
  --serve           安装并扫描后启动服务
  --skip-scan       只安装/改目录，不扫描
  --dir PATH        安装目录（默认 ~/deovr-library）
  --python PATH     指定 Python（默认 python3）
  --remote          强制按远程安装流程（拉取/更新到 --dir）
  -h, --help        显示帮助

环境变量:
  DEOVR_LIBRARY_HOME    安装目录（同 --dir）
  DEOVR_LIBRARY_REPO    GitHub 仓库 owner/name
  DEOVR_LIBRARY_BRANCH  分支（默认 main）

示例:
  curl -fsSL ${RAW_BASE}/install.sh | bash -s -- --demo --serve
  curl -fsSL ${RAW_BASE}/install.sh | bash -s -- --2d ~/Movies/2D --vr ~/Movies/VR --rewrite-to 192.168.0.34 --serve
EOF
}

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
    --dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --python) PY="${2:-}"; shift 2 ;;
    --remote) FORCE_REMOTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1"; usage; exit 1 ;;
  esac
done

INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

echo ""
echo "=============================="
echo " DeoVR Library 安装"
echo "=============================="
echo ""

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "警告: 当前不是 macOS（$(uname -s)），脚本仍会尝试继续。"
fi

is_repo_root() {
  [[ -f "$1/run_cli.py" && -f "$1/requirements.txt" ]]
}

resolve_root() {
  local src="${BASH_SOURCE[0]:-$0}"
  # curl | bash 时 src 通常是 "bash"，没有真实脚本路径
  if [[ "$FORCE_REMOTE" -eq 0 && -f "$src" && "$src" != "bash" && "$src" != "-" ]]; then
    local here
    here="$(cd "$(dirname "$src")" && pwd)"
    if is_repo_root "$here"; then
      echo "$here"
      return
    fi
  fi
  echo ""
}

prompt() {
  # curl|bash 时 stdin 是管道，交互必须读 /dev/tty
  local msg="$1"
  local reply=""
  if [[ -r /dev/tty ]]; then
    printf "%s" "$msg" > /dev/tty
    IFS= read -r reply < /dev/tty || true
  elif [[ -t 0 ]]; then
    printf "%s" "$msg"
    IFS= read -r reply || true
  fi
  printf "%s" "$reply"
}

ensure_tools() {
  if ! command -v curl >/dev/null 2>&1; then
    echo "需要 curl。"
    exit 1
  fi
  if ! command -v unzip >/dev/null 2>&1 && ! command -v git >/dev/null 2>&1; then
    echo "需要 git 或 unzip 之一。建议: xcode-select --install 或 brew install git"
    exit 1
  fi
}

fetch_repo() {
  ensure_tools
  echo "==> 安装目录: $INSTALL_DIR"

  if is_repo_root "$INSTALL_DIR"; then
    echo "==> 已存在仓库，更新代码..."
    if [[ -d "$INSTALL_DIR/.git" ]] && command -v git >/dev/null 2>&1; then
      git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH" 2>/dev/null || true
      if git -C "$INSTALL_DIR" rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
        git -C "$INSTALL_DIR" checkout -q "$BRANCH" 2>/dev/null || true
        git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || {
          echo "git pull 失败，保留现有代码继续安装。"
        }
      fi
    else
      echo "无 git 元数据，跳过更新（保留现有文件）。"
    fi
    return
  fi

  if [[ -e "$INSTALL_DIR" ]] && [[ ! -d "$INSTALL_DIR" || -n "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
    local ans
    ans="$(prompt "目录已存在且非空: $INSTALL_DIR ，是否覆盖安装？(y/N) ")"
    echo ""
    if [[ ! "$ans" =~ ^[Yy]$ ]]; then
      echo "取消安装"
      exit 0
    fi
    rm -rf "$INSTALL_DIR"
  fi

  mkdir -p "$(dirname "$INSTALL_DIR")"

  if command -v git >/dev/null 2>&1; then
    echo "==> git clone $GIT_URL ($BRANCH)"
    git clone --depth 1 --branch "$BRANCH" "$GIT_URL" "$INSTALL_DIR"
  else
    echo "==> 下载 ZIP: $ZIP_URL"
    local tmp zipdir
    tmp="$(mktemp -d)"
    zipdir="$tmp/repo.zip"
    curl -fSL --progress-bar "$ZIP_URL" -o "$zipdir"
    unzip -q "$zipdir" -d "$tmp"
    # GitHub archive 解压为 <repo>-<branch>
    local extracted
    extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
    mv "$extracted" "$INSTALL_DIR"
    rm -rf "$tmp"
  fi

  if ! is_repo_root "$INSTALL_DIR"; then
    echo "安装失败：未在 $INSTALL_DIR 找到 run_cli.py"
    exit 1
  fi
}

ROOT="$(resolve_root)"
if [[ -z "$ROOT" ]]; then
  echo "==> 远程安装模式（curl | bash）"
  fetch_repo
  ROOT="$INSTALL_DIR"
else
  echo "==> 本地仓库模式: $ROOT"
fi

cd "$ROOT"
chmod +x "$ROOT/install.sh" 2>/dev/null || true

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

  if [[ -z "$PATH_2D" && "$CLEAR_2D" -eq 0 ]]; then
    PATH_2D="$(prompt "固定 2D 目录路径（回车跳过）: ")"
    echo ""
  fi
  if [[ -z "$PATH_VR" && "$CLEAR_VR" -eq 0 ]]; then
    PATH_VR="$(prompt "固定 VR 目录路径（回车跳过）: ")"
    echo ""
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
      echo "  cd \"$ROOT\" && source .venv/bin/activate"
      echo "  python run_cli.py library set-2d --path DIR"
      echo "  python run_cli.py scan --force"
    fi
  fi
fi

LAN_IP="$("${CLI[@]}" config --show-only 2>/dev/null | awk -F': ' '/^rewrite_to:/{print $2; exit}')"
LAN_IP="${LAN_IP:-127.0.0.1}"

echo
echo "✅ 安装完成 → $ROOT"
echo "  进入目录:  cd \"$ROOT\""
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
echo
echo "再次一键安装/更新:"
echo "  curl -fsSL ${RAW_BASE}/install.sh | bash -s -- --skip-scan"

if [[ "$SERVE" -eq 1 ]]; then
  echo
  echo "==> 启动服务 :$PORT"
  exec "${CLI[@]}" serve --port "$PORT" --rewrite --rewrite-to "${REWRITE_TO:-$LAN_IP}"
fi

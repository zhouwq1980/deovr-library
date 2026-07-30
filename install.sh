#!/usr/bin/env bash
# DeoVR Library — 一键下载完整初始项目
#
#   curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash
#
# 只负责：拉取仓库 → 创建虚拟环境 → 安装依赖 → 初始化空配置。
# 片库目录 / 扫描 / 启服务请用图形界面：python run_gui.py
set -euo pipefail

REPO="${DEOVR_LIBRARY_REPO:-zhouwq1980/deovr-library}"
BRANCH="${DEOVR_LIBRARY_BRANCH:-main}"
INSTALL_DIR="${DEOVR_LIBRARY_HOME:-$HOME/deovr-library}"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
ZIP_URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.zip"
GIT_URL="https://github.com/${REPO}.git"

PY="${PYTHON:-}"
FORCE_REMOTE=0
SKIP_DEPS=0
UPDATE=0
FORCE_OVERWRITE=0

usage() {
  cat <<EOF
用法:
  curl -fsSL ${RAW_BASE}/install.sh | bash
  curl -fsSL ${RAW_BASE}/install.sh | bash -s -- [选项]
  ./install.sh [选项]

一键安装 = 下载完整初始项目到本机（默认 ~/deovr-library），并装好 Python 依赖。
若目标目录已有项目：默认保留原文件，不覆盖、不删除、不强制 git pull。
配置片库、扫描、启动请用 GUI：python run_gui.py

选项:
  --dir PATH        安装目录（默认 ~/deovr-library）
  --python PATH     指定 Python（默认 python3）
  --skip-deps       只下载/复用项目，不创建 venv / 不装依赖
  --update          已有 git 仓库时尝试 pull 更新代码（仍不删 data/ 等本地数据）
  --force           目录已占用且不是本项目时，允许清空后重装（危险）
  --remote          强制远程拉取到 --dir（忽略当前目录）
  -h, --help        显示帮助

环境变量:
  DEOVR_LIBRARY_HOME    安装目录（同 --dir）
  DEOVR_LIBRARY_REPO    GitHub 仓库 owner/name
  DEOVR_LIBRARY_BRANCH  分支（默认 main）
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --python) PY="${2:-}"; shift 2 ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --update) UPDATE=1; shift ;;
    --force) FORCE_OVERWRITE=1; shift ;;
    --remote) FORCE_REMOTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    # 兼容旧参数：忽略并提示（避免老文档一键命令直接失败）
    --2d|--vr|--rewrite-to|--port)
      echo "提示: 已忽略旧选项 $1（一键安装只下载项目；请用 GUI 配置）"
      shift 2 2>/dev/null || shift
      ;;
    --clear-2d|--clear-vr|--reset|--demo|--serve|--skip-scan)
      echo "提示: 已忽略旧选项 $1（一键安装只下载项目；请用 GUI 配置）"
      shift
      ;;
    *) echo "未知参数: $1"; usage; exit 1 ;;
  esac
done

INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

echo ""
echo "=============================="
echo " DeoVR Library 一键安装"
echo " 下载完整初始项目"
echo "=============================="
echo ""

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "警告: 当前不是 macOS（$(uname -s)），脚本仍会尝试继续。"
fi

is_repo_root() {
  [[ -f "$1/run_cli.py" && -f "$1/requirements.txt" && -f "$1/run_gui.py" ]]
}

resolve_root() {
  local src="${BASH_SOURCE[0]:-$0}"
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

  # 已是完整项目：默认原样复用，绝不覆盖本地文件
  if is_repo_root "$INSTALL_DIR"; then
    echo "==> 检测到已有项目，保留原文件（不覆盖）"
    if [[ "$UPDATE" -eq 1 ]]; then
      if [[ -d "$INSTALL_DIR/.git" ]] && command -v git >/dev/null 2>&1; then
        echo "==> --update：尝试 git pull（不删除 data/ 等未跟踪本地数据）"
        git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH" 2>/dev/null || true
        if git -C "$INSTALL_DIR" rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
          git -C "$INSTALL_DIR" checkout -q "$BRANCH" 2>/dev/null || true
          git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || {
            echo "git pull 失败，继续使用现有代码（未覆盖）。"
          }
        fi
      else
        echo "无 git 元数据，跳过 --update（保留现有文件）。"
      fi
    else
      echo "    如需拉取最新代码可加: bash -s -- --update"
    fi
    return
  fi

  # 目录已存在但不是本项目：默认不删、不覆盖
  if [[ -e "$INSTALL_DIR" ]]; then
    if [[ -d "$INSTALL_DIR" ]] && [[ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
      : # 空目录，可以装进去
    else
      if [[ "$FORCE_OVERWRITE" -eq 1 ]]; then
        echo "==> --force：将清空后重装 $INSTALL_DIR"
        rm -rf "$INSTALL_DIR"
      else
        echo "❌ 目录已存在且不是 DeoVR Library 项目（或文件不完整）:"
        echo "   $INSTALL_DIR"
        echo "为避免覆盖原文件，已中止。"
        echo "可选："
        echo "  1) 换目录:  bash -s -- --dir ~/deovr-library-new"
        echo "  2) 确认清空重装（危险）:  bash -s -- --force"
        exit 1
      fi
    fi
  fi

  mkdir -p "$(dirname "$INSTALL_DIR")"

  if command -v git >/dev/null 2>&1; then
    echo "==> git clone $GIT_URL ($BRANCH)"
    git clone --depth 1 --branch "$BRANCH" "$GIT_URL" "$INSTALL_DIR"
  else
    echo "==> 下载 ZIP: $ZIP_URL"
    local tmp zipdir extracted
    tmp="$(mktemp -d)"
    zipdir="$tmp/repo.zip"
    curl -fSL --progress-bar "$ZIP_URL" -o "$zipdir"
    unzip -q "$zipdir" -d "$tmp"
    extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
    mv "$extracted" "$INSTALL_DIR"
    rm -rf "$tmp"
  fi

  if ! is_repo_root "$INSTALL_DIR"; then
    echo "安装失败：未在 $INSTALL_DIR 找到完整项目文件"
    exit 1
  fi
}

ROOT="$(resolve_root)"
if [[ -z "$ROOT" ]]; then
  echo "==> 远程下载模式"
  fetch_repo
  ROOT="$INSTALL_DIR"
else
  echo "==> 本地仓库模式: $ROOT"
fi

cd "$ROOT"
chmod +x "$ROOT/install.sh" "$ROOT/run_gui.py" 2>/dev/null || true

if [[ "$SKIP_DEPS" -eq 1 ]]; then
  echo
  echo "✅ 项目已就绪 → $ROOT"
  echo "  （已跳过依赖安装）"
  echo "  手动: cd \"$ROOT\" && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  echo "  然后: python run_gui.py"
  exit 0
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
else
  echo "==> 复用已有虚拟环境 .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip wheel >/dev/null
echo "==> 安装/更新依赖"
python -m pip install -r requirements.txt
if [[ -f data/config.json ]]; then
  echo "==> 已有 data/config.json，跳过 init（保留本地配置）"
else
  echo "==> 初始化空配置"
  python run_cli.py init >/dev/null || true
fi

echo
echo "✅ 项目就绪 → $ROOT"
if is_repo_root "$ROOT"; then
  echo "  （已有项目时默认不覆盖源码与本地 data/）"
fi
echo
echo "接下来用图形界面配置片库并启动："
echo "  cd \"$ROOT\""
echo "  source .venv/bin/activate"
echo "  python run_gui.py"
echo
echo "命令行亦可："
echo "  python run_cli.py library set-2d --path \"/你的/2D目录\""
echo "  python run_cli.py scan --force"
echo "  python run_cli.py serve --port 8765"
echo
echo "再次更新项目："
echo "  curl -fsSL ${RAW_BASE}/install.sh | bash"

#!/usr/bin/env bash
# DeoVR Library — 一键下载 / 覆盖更新核心项目文件
#
#   curl -fsSL https://raw.githubusercontent.com/zhouwq1980/deovr-library/main/install.sh | bash
#
# 已有项目：覆盖安装所有核心源码/文档/脚本；保留本地数据：
#   data/config.json、data/library.db*、data/thumbs/、.venv/
# 片库配置 / 扫描 / 启服务请用：python run_gui.py
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
KEEP_CODE=0
FORCE_OVERWRITE=0

usage() {
  cat <<EOF
用法:
  curl -fsSL ${RAW_BASE}/install.sh | bash
  curl -fsSL ${RAW_BASE}/install.sh | bash -s -- [选项]
  ./install.sh [选项]

一键安装到 ~/deovr-library（可用 --dir 改）：
  · 首次：下载完整项目并安装依赖
  · 已有项目：覆盖更新全部核心文件（源码/脚本/文档等）
  · 始终保留本地数据：data/config.json、library.db、thumbs/、.venv/

选项:
  --dir PATH        安装目录（默认 ~/deovr-library）
  --python PATH     指定 Python（默认 python3）
  --skip-deps       不创建/更新 venv 依赖
  --keep-code       已有项目时不覆盖核心文件（仅补依赖）
  --force           目录已占用且不是本项目时，允许清空后重装（危险）
  --remote          强制按 --dir 远程安装（忽略当前目录）
  -h, --help        显示帮助

环境变量:
  DEOVR_LIBRARY_HOME / DEOVR_LIBRARY_REPO / DEOVR_LIBRARY_BRANCH
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --python) PY="${2:-}"; shift 2 ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --keep-code) KEEP_CODE=1; shift ;;
    --force) FORCE_OVERWRITE=1; shift ;;
    --remote) FORCE_REMOTE=1; shift ;;
    --update)
      # 兼容旧参数：现在默认就会覆盖更新核心文件
      echo "提示: 已默认覆盖更新核心文件，--update 可省略"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    --2d|--vr|--rewrite-to|--port)
      echo "提示: 已忽略旧选项 $1（请用 GUI 配置）"
      shift 2 2>/dev/null || shift
      ;;
    --clear-2d|--clear-vr|--reset|--demo|--serve|--skip-scan)
      echo "提示: 已忽略旧选项 $1（请用 GUI 配置）"
      shift
      ;;
    *) echo "未知参数: $1"; usage; exit 1 ;;
  esac
done

INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

echo ""
echo "=============================="
echo " DeoVR Library 一键安装"
echo " 核心文件覆盖 · 本地数据保留"
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

# 从 GitHub ZIP 覆盖核心文件，显式跳过本地数据
overlay_core_from_zip() {
  local dest="$1"
  local tmp zipdir extracted
  ensure_tools
  if ! command -v unzip >/dev/null 2>&1; then
    echo "覆盖核心文件需要 unzip（或改用带 .git 的安装以便 git reset）"
    return 1
  fi
  echo "==> 下载最新核心文件并覆盖安装…"
  tmp="$(mktemp -d)"
  zipdir="$tmp/repo.zip"
  curl -fSL --progress-bar "$ZIP_URL" -o "$zipdir"
  unzip -q "$zipdir" -d "$tmp"
  extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
  if [[ -z "$extracted" || ! -d "$extracted" ]]; then
    rm -rf "$tmp"
    echo "ZIP 解压失败"
    return 1
  fi

  mkdir -p "$dest/data"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude '.venv/' \
      --exclude 'data/config.json' \
      --exclude 'data/library.db' \
      --exclude 'data/library.db-'* \
      --exclude 'data/thumbs/' \
      --exclude '.git/' \
      "$extracted"/ "$dest"/
  else
    # 无 rsync：逐项覆盖核心路径，不动本地 data 私有文件与 .venv
    local item
    for item in "$extracted"/* "$extracted"/.[!.]*; do
      [[ -e "$item" ]] || continue
      local base
      base="$(basename "$item")"
      case "$base" in
        .venv|.git) continue ;;
        data)
          mkdir -p "$dest/data"
          local f
          for f in "$item"/*; do
            [[ -e "$f" ]] || continue
            local bn
            bn="$(basename "$f")"
            case "$bn" in
              config.json|library.db|thumbs) continue ;;
            esac
            [[ "$bn" == library.db-* ]] && continue
            rm -rf "$dest/data/$bn"
            cp -R "$f" "$dest/data/$bn"
          done
          ;;
        *)
          rm -rf "$dest/$base"
          cp -R "$item" "$dest/$base"
          ;;
      esac
    done
  fi

  rm -rf "$tmp"
  echo "==> 核心文件已覆盖；已保留 data/config.json、library.db、thumbs/、.venv/"
}

# 已有项目：用 git 硬重置到远端，覆盖全部已跟踪核心文件；gitignore 本地数据不受影响
update_core_files() {
  local dest="$1"
  if [[ "$KEEP_CODE" -eq 1 ]]; then
    echo "==> --keep-code：跳过核心文件覆盖"
    return 0
  fi

  echo "==> 已有项目：覆盖安装核心文件（保留本地 data/ 与 .venv）"

  if [[ -d "$dest/.git" ]] && command -v git >/dev/null 2>&1; then
    if git -C "$dest" remote get-url origin >/dev/null 2>&1; then
      echo "==> git fetch + reset --hard origin/$BRANCH"
      if git -C "$dest" fetch --depth 1 origin "$BRANCH" \
        && git -C "$dest" checkout -q "$BRANCH" 2>/dev/null \
        && git -C "$dest" reset --hard "origin/$BRANCH"; then
        echo "==> 核心文件已用 git 覆盖更新"
        return 0
      fi
      echo "git 更新失败，改用 ZIP 覆盖核心文件…"
    fi
  fi

  overlay_core_from_zip "$dest"
}

fetch_repo() {
  ensure_tools
  echo "==> 安装目录: $INSTALL_DIR"

  if is_repo_root "$INSTALL_DIR"; then
    update_core_files "$INSTALL_DIR"
    return
  fi

  if [[ -e "$INSTALL_DIR" ]]; then
    if [[ -d "$INSTALL_DIR" ]] && [[ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
      :
    else
      if [[ "$FORCE_OVERWRITE" -eq 1 ]]; then
        echo "==> --force：清空后重装 $INSTALL_DIR"
        rm -rf "$INSTALL_DIR"
      else
        echo "❌ 目录已存在且不是 DeoVR Library 项目:"
        echo "   $INSTALL_DIR"
        echo "为避免误删其它文件，已中止。"
        echo "  换目录: bash -s -- --dir ~/deovr-library-new"
        echo "  或强制清空: bash -s -- --force"
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
  echo "==> 远程安装模式"
  fetch_repo
  ROOT="$INSTALL_DIR"
else
  echo "==> 本地仓库模式: $ROOT"
  # 在已有 clone 里执行 ./install.sh 时同样覆盖核心文件
  if [[ "$KEEP_CODE" -eq 0 ]]; then
    ensure_tools
    update_core_files "$ROOT"
  fi
fi

cd "$ROOT"
chmod +x "$ROOT/install.sh" "$ROOT/run_gui.py" 2>/dev/null || true

if [[ "$SKIP_DEPS" -eq 1 ]]; then
  echo
  echo "✅ 项目已就绪 → $ROOT"
  echo "  （已跳过依赖安装）"
  echo "  然后: cd \"$ROOT\" && source .venv/bin/activate && python run_gui.py"
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
  echo "==> 已有 data/config.json，跳过 init（保留本地片库配置）"
else
  echo "==> 初始化空配置"
  python run_cli.py init >/dev/null || true
fi

echo
echo "✅ 项目就绪 → $ROOT"
echo "  核心文件：已覆盖为 GitHub 最新"
echo "  本地保留：data/config.json · library.db · thumbs/ · .venv/"
echo
echo "接下来用图形界面配置片库并启动："
echo "  cd \"$ROOT\""
echo "  source .venv/bin/activate"
echo "  python run_gui.py"
echo
echo "再次覆盖更新核心文件："
echo "  curl -fsSL ${RAW_BASE}/install.sh | bash"

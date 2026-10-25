#!/usr/bin/env bash
# ReasoningBank 复现环境安装脚本（在 WSL2 / Ubuntu 里执行）
#
#   bash scripts/setup_wsl.sh
#
# 做四件事：装 uv + Python 3.12（代码 pyproject 写 3.13，但 browsergym 0.14.1 锁了
# playwright==1.44.0 -> greenlet==3.0.3，这个版本没有 3.13 的 wheel，3.12 最稳）、
# 装依赖、装 Chromium、生成 812 个任务配置文件。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
echo "[1/6] repo: $REPO_DIR"

# ---------------------------------------------------------------- Docker 检查
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    echo "[ok] docker 可用: $(docker --version)"
  else
    echo "[warn] 有 docker 命令但连不上 daemon；先启动 Docker Desktop 并打开 WSL Integration"
  fi
else
  echo "[warn] 没找到 docker 命令；WebArena 任务需要它（Docker Desktop + WSL Integration）"
fi

# ---------------------------------------------------------------- 系统依赖
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq curl ca-certificates build-essential git >/dev/null
fi

# ---------------------------------------------------------------- uv
if ! command -v uv >/dev/null 2>&1; then
  echo "[2/6] 安装 uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh || python3 -m pip install --user uv
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

# ---------------------------------------------------------------- Python + venv
echo "[3/6] 创建 venv (Python 3.12)"
uv python install 3.12
uv venv --python 3.12 .venv
PY="$REPO_DIR/.venv/bin/python"

# ---------------------------------------------------------------- 依赖
echo "[4/6] 安装依赖（约 1.5GB，含 torch / sentence-transformers）"
IDX="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"   # 想换源就 export PIP_INDEX_URL
uv pip install -r requirements.txt --python "$PY" --index-url "$IDX"
uv pip install -r requirements-swe.txt --python "$PY" --index-url "$IDX"

# ---------------------------------------------------------------- 浏览器
echo "[5/6] 安装 Playwright Chromium（--with-deps 会调 apt，可能要输 sudo 密码）"
export PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://cdn.npmmirror.com/binaries/playwright}"
"$PY" -m playwright install --with-deps chromium

# ---------------------------------------------------------------- 任务配置
echo "[6/6] 生成任务配置"
mkdir -p models
if [ ! -f .env ]; then
  cp .env.example .env
  echo "!! 已生成 .env，请先填 RB_CHAT_* / RB_EMBED_* / WA_*，再重新跑本脚本最后一步"
fi
set -a; . ./.env; set +a
for k in SHOPPING SHOPPING_ADMIN REDDIT GITLAB WIKIPEDIA MAP HOMEPAGE; do
  v="WA_$k"; [ -n "${!v:-}" ] && export "$k=${!v}"
done
cp -n third_party/webarena/test.raw.json WebArena/config_files/test.raw.json
(cd WebArena/config_files && "$PY" generate_config_files.py)
echo "任务配置数量: $(ls WebArena/config_files | grep -c '^[0-9]*\.json$')  (应该是 812)"

cat <<EOF

安装完成。下一步：
  source .venv/bin/activate
  export PYTHONPATH="$REPO_DIR/third_party:\$PYTHONPATH"
  python scripts/smoke_offline.py          # 不花钱的自检
  bash scripts/run_webarena.sh 0 3         # 跑 shopping 前 3 个任务（需要先起 docker）
EOF

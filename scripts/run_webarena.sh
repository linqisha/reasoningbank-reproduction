#!/usr/bin/env bash
# 在 WSL2 / Linux 里跑 WebArena 的 ReasoningBank 闭环：
#   bash scripts/run_webarena.sh <start_index> <end_index> [website]
# 例如：bash scripts/run_webarena.sh 0 3 shopping
#
# 每个任务依次执行三步（pipeline_memory.py 内部完成）：
#   1) run.py             -> 跑任务，产出 results/webarena.<id>/
#   2) autoeval           -> LLM 判分，产出 <model>_autoeval.json
#   3) induce_memory.py   -> 从轨迹提炼记忆，追加到 memories_reasoningbank/<website>.jsonl
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
START="${1:-0}"
END="${2:-3}"
WEBSITE="${3:-shopping}"

cd "$REPO_DIR"
set -a; . ./.env; set +a
export PYTHONPATH="$REPO_DIR/third_party:${PYTHONPATH:-}"
for k in SHOPPING SHOPPING_ADMIN REDDIT GITLAB WIKIPEDIA MAP HOMEPAGE; do
  v="WA_$k"; [ -n "${!v:-}" ] && export "$k=${!v}"
done

# 先确认网站是通的（shopping 容器没起就别浪费时间）
python - "$WEBSITE" <<'PY'
import os, sys, urllib.request
site = sys.argv[1]
url = {"shopping": os.environ.get("WA_SHOPPING"),
       "shopping_admin": (os.environ.get("WA_SHOPPING_ADMIN") or "").replace("/admin", ""),
       "reddit": os.environ.get("WA_REDDIT"),
       "gitlab": os.environ.get("WA_GITLAB")}.get(site)
if not url:
    print(f"[warn] 没有为 {site} 配置 WA_* 地址，跳过连通性检查")
    raise SystemExit(0)
try:
    code = urllib.request.urlopen(url, timeout=10).status
    print(f"[ok] {site} {url} -> HTTP {code}")
except Exception as e:
    print(f"[error] {site} {url} 不可达: {e}")
    print("        先起 docker 容器，见 REPRODUCE.md 4.4")
    raise SystemExit(1)
PY

cd WebArena
MODEL="${RB_CHAT_MODEL:-deepseek-chat}"
OUT="${OUT:-./results}"                  # 输出目录：对照组用 OUT=./results_nomem
MEM_MODE="${MEM_MODE:-reasoningbank}"    # no_memory | reasoningbank | awm | synapse
JUDGE="${JUDGE:-autoeval}"               # autoeval（LLM 判分）| gt（真实评分器）

mkdir -p "memories_${MEM_MODE}" "$OUT"

python pipeline_memory.py \
  --website "$WEBSITE" \
  --model "$MODEL" \
  --output_dir "$OUT" \
  --start_index "$START" \
  --end_index "$END" \
  --memory_mode "$MEM_MODE" \
  --judge "$JUDGE"

echo "完成。结果在 WebArena/${OUT#./}，记忆在 WebArena/memories_${MEM_MODE}/${WEBSITE}.jsonl"

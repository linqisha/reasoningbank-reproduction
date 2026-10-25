"""诊断"记忆为什么没注入"。

排查链路：bank(记忆库) → cache(向量缓存) → embedder(维度) → screening(检索) → select_memory(命中)

用法（在 WebArena 目录下）：

    python ../scripts/debug_memory.py            # 默认用 143 的 query 试
    python ../scripts/debug_memory.py 117        # 指定任务

注意：screening() 会往缓存里追加一条当前 query 的 embedding（原代码就是这么写的），
所以这脚本会改动 shopping_embeddings.jsonl 一行，无副作用但要知道。
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())  # 让 memory_management / utils 可 import

from memory_management import load_cached_embeddings, screening, select_memory  # noqa: E402
from utils.reasoningbank_llm import describe, get_embedder  # noqa: E402

BASE = Path("memories_reasoningbank")
SITE = "shopping"
BANK = BASE / f"{SITE}.jsonl"
CACHE = BASE / f"{SITE}_embeddings.jsonl"
TXT = BASE / f"{SITE}.txt"

task = sys.argv[1] if len(sys.argv) > 1 else "143"


def show(title):
    print(f"\n--- {title} ---")


show("环境")
print(describe())

show("记忆库 bank")
if BANK.is_file():
    bank = [json.loads(line) for line in BANK.read_text().splitlines() if line.strip()]
    print(f"条数 = {len(bank)}")
    print("task_id 列表 =", [b.get("task_id") for b in bank])
    if bank:
        print("第一条 status =", bank[0].get("status"))
        items = bank[0].get("memory_items") or []
        print("第一条 memory_items[0] 前 120 字 =", str(items[0])[:120] if items else "(空)")
else:
    bank = []
    print("文件不存在")

show("向量缓存 cache")
if CACHE.is_file():
    rows = [json.loads(line) for line in CACHE.read_text().splitlines() if line.strip()]
    print(f"条数 = {len(rows)}")
    print("id 列表 =", [r.get("id") for r in rows])
    print("维度分布 =", sorted({len(r["embedding"]) for r in rows}))
    print("model 字段 =", sorted({str(r.get("model")) for r in rows}))
else:
    rows = []
    print("文件不存在")

show("embedder")
embedder = get_embedder()
print("当前 embedder =", embedder, "| dim =", embedder.dim)
if CACHE.is_file():
    ids, texts, emb = load_cached_embeddings(str(CACHE), dim=embedder.dim)
    print(f"按当前维度过滤后剩 {len(ids)} 条（0 条 = 检索必然为空）")

show(f"用 task {task} 的 intent 做一次检索")
config = Path("config_files") / f"{task}.json"
if not config.is_file():
    print(f"{config} 不存在，跳过")
else:
    intent = json.loads(config.read_text())["intent"]
    print("query =", intent)
    id2score, ordered = screening(intent, str(CACHE), task_id="9999", prefer_model="gemini")
    print("top5 =", id2score[:5])
    print("ordered_ids =", ordered[:5])
    picked = select_memory(1, bank, intent, "9999", str(CACHE), "gemini")
    print("select_memory 命中 =", len(picked), "条")
    if picked:
        print("命中 task_id =", picked[0].get("task_id"))

show("上次运行留下的 shopping.txt")
if TXT.is_file():
    content = TXT.read_text()
    print(f"长度 = {len(content)}")
    print("内容前 200 字 =", repr(content[:200]))
else:
    print("文件不存在（run.py 没写过，说明 select_memory 返回空）")

print("\n结论提示：")
print("  bank=20 但 cache 为空/维度不匹配 → 检索必然空 → txt 为空 → 不注入")
print("  cache 有数据但 select_memory 命中 0 → 命中逻辑问题（id 对不上）")

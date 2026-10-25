"""不花钱的自检脚本：不调用任何 API，验证补丁后的代码能不能 import、检索闭环能不能跑通。

用法（仓库根目录，WSL 或 Windows 都行）：
    python scripts/smoke_offline.py

它会检查：
1. config_files 是否已生成（812 个任务）
2. run.py / memory_management / clients 能否在「没有任何 Google 凭据」的情况下 import
3. 记忆检索闭环：第一次无记忆 -> 写入 embedding 缓存 -> 第二次能召回第一条
4. 当前 .env 的模型配置摘要（不会打印 key）
"""

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEBARENA = REPO / "WebArena"

# 自检默认用离线的 hash embedding，避免没钱/没网时被卡住
os.environ.setdefault("RB_EMBED_PROVIDER", "hash")
os.environ.setdefault("PYTHONPATH", str(REPO / "third_party"))

sys.path.insert(0, str(WEBARENA))
os.chdir(WEBARENA)

failures = []


def check(name, fn):
    try:
        detail = fn()
        print(f"[ok]   {name}" + (f" — {detail}" if detail else ""))
    except Exception as exc:
        failures.append((name, exc))
        print(f"[FAIL] {name} — {type(exc).__name__}: {exc}")


def check_configs():
    files = [p for p in (WEBARENA / "config_files").glob("*.json") if p.stem.isdigit()]
    if not files:
        raise RuntimeError("config_files 里没有任务 json，先跑 config_files/generate_config_files.py")
    if len(files) < 800:
        raise RuntimeError(f"只有 {len(files)} 个任务，WebArena 应该是 812 个")
    return f"{len(files)} 个任务"


def check_imports():
    import memory_management  # noqa: F401
    import run  # noqa: F401  （会连带 import browsergym / agents / webarena_patch）
    from utils.clients import get_client
    from utils.reasoningbank_llm import get_embedder, describe

    get_embedder()  # 触发 embedder 构造
    get_client("deepseek-chat")  # 只构造 client，不发请求
    return describe()


def check_memory_loop():
    from memory_management import select_memory

    bank = [
        {"task_id": "1", "query": "find the cheapest red shoe", "memory_items": ["A"]},
        {"task_id": "2", "query": "add this item to my wishlist", "memory_items": ["B"]},
    ]
    # 注意：不要在 Windows 沙箱里用 tempfile.TemporaryDirectory()（%TEMP% 可能不可写），
    # 直接用仓库内的临时目录更稳。
    tmp = REPO / ".tmp-smoke"
    tmp.mkdir(exist_ok=True)
    cache = str(tmp / "shopping_embeddings.jsonl")
    if os.path.exists(cache):
        os.remove(cache)
    first = select_memory(1, bank, "cheapest red shoes under 50 dollars", "1", cache, "gemini")
    second = select_memory(1, bank, "put this product into the wishlist", "2", cache, "gemini")
    if first:
        raise RuntimeError("第一次检索应该是空的（缓存里还没有历史）")
    if not second:
        raise RuntimeError("第二次检索应该有结果")
    if second[0]["task_id"] != "1":
        raise RuntimeError(f"召回错了：{second[0]['task_id']}（hash embedding 下期望 1）")
    return f"召回 task_id={second[0]['task_id']}"


print(f"repo: {REPO}")
check("任务配置", check_configs)
check("模块 import + 模型配置", check_imports)
check("记忆检索闭环", check_memory_loop)

if failures:
    print(f"\n{len(failures)} 项失败")
    sys.exit(1)
print("\n自检通过：代码骨架和记忆闭环都没问题，可以接真实模型了。")

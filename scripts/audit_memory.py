"""审计一批 WebArena 运行到底有没有注入记忆。

回答一个致命问题：**results_mem 里那些任务，真的都带上记忆跑的吗？**

用法（在 WebArena 目录下）：

    python ../scripts/audit_memory.py results_mem results_nomem

对每个任务打印：
    task  注入?  记忆条数  第一条记忆的标题
最后给出覆盖率：N/M 个任务真的注入了记忆。

判定方法：读 step_1.pkl.gz 里 system prompt（chat_messages[0]），
找 "Below are some memory items" 这句引导语；有就说明注入了，
再按 "# Memory Item" 数一下条数、抽出 Title。
"""

import gzip
import pickle
import re
import sys
from pathlib import Path

INTRO = "Below are some memory items"
ITEM_RE = re.compile(r"# Memory Item \d+\s*\n## Title\s*(.+)")
COUNT_RE = re.compile(r"# Memory Item \d+")


def first_system_prompt(task_dir: Path) -> str:
    step = task_dir / "step_1.pkl.gz"
    if not step.is_file():
        steps = sorted(task_dir.glob("step_*.pkl.gz"))
        if not steps:
            return ""
        step = steps[0]
    with gzip.open(step, "rb") as fh:
        data = pickle.load(fh)
    ai = data.get("agent_info", {}) if isinstance(data, dict) else getattr(data, "agent_info", {}) or {}
    messages = ai.get("chat_messages") or []
    return str(messages[0]) if messages else ""


def audit(root: str):
    root_path = Path(root)
    dirs = sorted(root_path.glob("webarena.*"), key=lambda p: int(p.name.split(".")[-1]))
    if not dirs:
        print(f"{root}: 没有任务目录")
        return

    print(f"\n=== {root} ===")
    print(f"{'task':>6}  {'注入':<4} {'条数':>4}  第一条标题")
    injected = 0
    for d in dirs:
        prompt = first_system_prompt(d)
        task = d.name.split(".")[-1]
        if INTRO in prompt:
            injected += 1
            count = len(COUNT_RE.findall(prompt))
            m = ITEM_RE.search(prompt)
            title = " ".join(m.group(1).split())[:60] if m else "-"
            print(f"{task:>6}  {'✅':<4} {count:>4}  {title}")
        else:
            print(f"{task:>6}  {'❌':<4} {0:>4}  -")

    print(f"\n覆盖：{injected}/{len(dirs)} 个任务真的注入了记忆")
    if injected < len(dirs) * 0.5:
        print("⚠️  超过一半的任务没有记忆 —— 这组的 A/B 对比不成立")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for root in sys.argv[1:]:
        audit(root)


if __name__ == "__main__":
    main()

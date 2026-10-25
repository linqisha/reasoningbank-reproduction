"""把一次 WebArena 运行的轨迹打印出来（含注入的记忆、每步 think/action）。

用来回答一个具体问题：**记忆到底有没有影响 agent 的行为？**

用法（在 WebArena 目录下）：

    python ../scripts/inspect_traj.py results_mem/webarena.117
    python ../scripts/inspect_traj.py results_mem/webarena.117 results_nomem/webarena.117

每个任务打印：
  1. 注入到 system prompt 里的记忆片段（如果有）
  2. 每一步的 think（截断）+ action
  3. 汇总：步数、提到记忆的步数、最终交卷内容
"""

import gzip
import pickle
import re
import sys
from pathlib import Path

MEM_BLOCK_RE = re.compile(r"Below are some memory items.*\Z", re.S)
MENTION_RE = re.compile(r"memory item|memory items|per memory|记忆", re.I)


def load_steps(folder: Path):
    files = sorted(
        [f for f in folder.iterdir() if re.fullmatch(r"step_\d+\.pkl\.gz", f.name)],
        key=lambda f: int(re.findall(r"\d+", f.name)[0]),
    )
    steps = []
    for f in files:
        with gzip.open(f, "rb") as fh:
            steps.append(pickle.load(fh))
    return steps


def get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def show(folder: Path, think_chars: int = 320):
    steps = load_steps(folder)
    if not steps:
        print(f"{folder}: 没有 step 文件")
        return

    print(f"\n{'=' * 70}\n{folder}  ({len(steps)} steps)\n{'=' * 70}")

    # 1) 注入的记忆（system prompt 里那一段）
    first_ai = get(steps[0], "agent_info", {}) or {}
    messages = first_ai.get("chat_messages") or []
    if messages:
        m = MEM_BLOCK_RE.search(str(messages[0]))
        if m:
            block = m.group(0)
            print("[注入的记忆]")
            print("  " + block[:600].replace("\n", "\n  "))
        else:
            print("[注入的记忆] 无（no_memory 或检索为空）")

    # 2) 每步
    mentions = 0
    for i, s in enumerate(steps, 1):
        ai = get(s, "agent_info", {}) or {}
        think = (ai.get("think") or "").strip()
        if not think:
            # 有些模型把思考写在 <think> 里，agent 没解析出来
            msgs = ai.get("chat_messages") or []
            if len(msgs) >= 3:
                raw = str(msgs[2])
                k = raw.find("<action>")
                think = re.sub(r"</?think>", "", raw[:k]).strip() if k > 0 else ""
        action = (ai.get("action") or "").strip()
        hit = bool(MENTION_RE.search(think))
        mentions += hit
        think_short = " ".join(think.split())[:think_chars]
        print(f"\n[{i}] {'🧠 ' if hit else ''}think: {think_short}")
        print(f"    action: {' '.join(action.split())[:200]}")

    # 3) 汇总
    last = get(steps[-1], "agent_info", {}) or {}
    final = " ".join(str(last.get("action") or "").split())[:300]
    print(f"\n[汇总] 步数={len(steps)}  提到记忆的步数={mentions}")
    print(f"[汇总] 最终 action: {final}")


def main() -> None:
    dirs = sys.argv[1:]
    if not dirs:
        raise SystemExit(__doc__)
    for d in dirs:
        p = Path(d)
        if not p.is_dir():
            print(f"[skip] 目录不存在: {d}")
            continue
        show(p)


if __name__ == "__main__":
    main()

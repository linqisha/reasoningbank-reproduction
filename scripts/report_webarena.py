"""汇总 WebArena 跑分：逐任务奖励 + 成功率，可对比两组实验。

用法（在 WebArena 目录下）：

    python ../scripts/report_webarena.py results                 # 单组
    python ../scripts/report_webarena.py results_nomem results_mem   # 两组对比

注意：`cum_reward` 是 WebArena 自带的评测器（string_match / program_html 等）算的
GT 奖励，不是 autoeval 的 LLM 判断。两者可能不一致，autoeval 结果在
`<result_dir>/<model>_autoeval.json`。
"""

import json
import sys
from pathlib import Path


def load(root: str) -> dict:
    root_path = Path(root)
    if not root_path.is_dir():
        raise SystemExit(f"目录不存在: {root}")
    rows = {}
    for d in sorted(root_path.glob("webarena.*")):
        summary = d / "summary_info.json"
        if not summary.is_file():
            continue
        task = d.name.split(".")[-1]
        info = json.loads(summary.read_text())
        rows[task] = {
            "reward": info.get("cum_reward"),
            "steps": info.get("n_steps"),
            "err": info.get("err_msg"),
        }
    return rows


def summarize(name: str, rows: dict) -> str:
    if not rows:
        return f"{name}: 没有结果"
    ok = sum(1 for r in rows.values() if r["reward"] == 1.0)
    errs = [t for t, r in rows.items() if r["err"]]
    avg_steps = sum((r["steps"] or 0) for r in rows.values()) / len(rows)
    return (f"{name}: {ok}/{len(rows)} 成功 ({ok / len(rows) * 100:.0f}%) | "
            f"平均步数 {avg_steps:.1f} | 异常 {len(errs)}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    groups = [(Path(a).name, load(a)) for a in sys.argv[1:]]

    for name, rows in groups:
        print(f"\n=== {name} ===")
        for task, r in rows.items():
            mark = "✅" if r["reward"] == 1.0 else "❌"
            extra = f"  err={r['err']}" if r["err"] else ""
            print(f"  {mark} task {task:>4}  steps={r['steps']}{extra}")

    print()
    for name, rows in groups:
        print(summarize(name, rows))

    if len(groups) == 2:
        (n1, r1), (n2, r2) = groups
        common = sorted(set(r1) & set(r2), key=lambda x: int(x))
        if common:
            only1 = [t for t in common if r1[t]["reward"] == 1.0 and r2[t]["reward"] != 1.0]
            only2 = [t for t in common if r2[t]["reward"] == 1.0 and r1[t]["reward"] != 1.0]
            print(f"\n共同任务 {len(common)} 个：{n1} 独赢 {len(only1)} 个，{n2} 独赢 {len(only2)} 个")
            if only1:
                print(f"  仅 {n1} 做对: {', '.join(only1)}")
            if only2:
                print(f"  仅 {n2} 做对: {', '.join(only2)}")


if __name__ == "__main__":
    main()

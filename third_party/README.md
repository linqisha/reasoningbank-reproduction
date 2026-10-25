# mini-swe-agent (vendored copy used by ReasoningBank)

This directory is a trimmed copy of [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)
that ReasoningBank extends with a reasoning-memory pipeline
(`src/minisweagent/memory/`, `src/minisweagent/run/extra/swebench.py`).

`pyproject.toml` refers to a `README.md` and a `LICENSE.md` that were missing from the
released snapshot, which makes `pip install -e .` fail. `LICENSE.md` is now a copy of the
repository's Apache-2.0 license; this file satisfies the `readme` field.

Install (from the repository root):

```bash
uv pip install -e ./third_party --python .venv/bin/python
```

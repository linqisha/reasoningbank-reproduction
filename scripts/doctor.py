"""环境体检：一条命令看清「装到哪一步了、还差什么」。

用法（WSL / Linux，仓库根目录）：

    python scripts/doctor.py            # 本地检查，不花钱、不联网
    python scripts/doctor.py --net      # 额外发一次极小的 API 请求（约 20 token）

退出码 0 = 关键项全通；1 = 有阻断项（会标出来）。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OK, BAD, WARN = "✅", "❌", "⚠️ "
results = []          # (level, name, detail)
blockers = []


def add(level, name, detail=""):
    results.append((level, name, detail))
    if level == BAD:
        blockers.append(name)


def check(name, fn, level_on_fail=BAD, hint=""):
    try:
        detail = fn()
        add(OK, name, detail or "")
    except Exception as exc:
        add(level_on_fail, name, f"{type(exc).__name__}: {exc}" + (f" | {hint}" if hint else ""))


# --------------------------------------------------------------------------- #
def venv_python():
    version = sys.version.split()[0]
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"当前 Python {version}，建议 3.12（3.13 在 Windows 上装不了 greenlet 3.0.3）")
    if not str(REPO / ".venv") in sys.executable:
        return f"{version}（没在 .venv 里，注意用的是哪个解释器）"
    return version


def env_file():
    path = REPO / ".env"
    if not path.is_file():
        raise FileNotFoundError("缺 .env（cp .env.example .env 再填）")
    sys.path.insert(0, str(REPO / "WebArena"))
    from utils.reasoningbank_llm import describe  # noqa: E402
    return describe()


def key_masked():
    sys.path.insert(0, str(REPO / "WebArena"))
    from utils.reasoningbank_llm import chat_api_key  # noqa: E402

    key = chat_api_key()
    if not key:
        raise RuntimeError("RB_CHAT_API_KEY 没设置")
    return f"{key[:6]}…{key[-4:]}（{len(key)} 字符）"


def imports():
    mods = ["torch", "transformers", "openai", "browsergym.experiments", "langchain_openai"]
    missing = []
    for m in mods:
        try:
            __import__(m)
        except Exception as exc:
            missing.append(f"{m}({type(exc).__name__})")
    if missing:
        raise RuntimeError("缺: " + ", ".join(missing))
    import torch
    return f"torch {torch.__version__}, cuda={'可用' if torch.cuda.is_available() else '不可用'}"


def local_embedding():
    from sentence_transformers import SentenceTransformer  # noqa: F401

    dirs = [REPO / "models" / n for n in ("bge-m3", "bge-large-en-v1.5", "bge-small")]
    found = [d.name for d in dirs if d.is_dir()]
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    cached = [p.name for p in cache.glob("models--BAAI--*")] if cache.is_dir() else []
    return f"本地目录={found or '无'}, HF 缓存={cached or '无'}（首次运行会自动下载 bge-m3 2.2GB）"


def task_configs():
    files = [p for p in (REPO / "WebArena" / "config_files").glob("*.json") if p.stem.isdigit()]
    if len(files) < 800:
        raise RuntimeError(f"只有 {len(files)} 个任务，应该 812（跑过 setup_wsl.sh 吗）")
    return f"{len(files)} 个任务"


def chromium():
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    candidates = [Path(root)] if root else [Path.home() / ".cache" / "ms-playwright"]
    for c in candidates:
        if c.is_dir() and any(p.name.startswith("chromium") for p in c.iterdir()):
            return str(c)
    raise RuntimeError("没找到 chromium，跑 `python -m playwright install --with-deps chromium`")


def docker_daemon():
    exe = shutil.which("docker")
    if not exe:
        raise RuntimeError("没有 docker 命令（Docker Desktop 没装或 WSL Integration 没开）")
    out = subprocess.run([exe, "info"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("docker 命令在但连不上 daemon（启动 Docker Desktop？）")
    return "daemon 正常"


def docker_image(tag):
    def _inner():
        exe = shutil.which("docker")
        if not exe:
            raise RuntimeError("无 docker")
        out = subprocess.run([exe, "image", "inspect", tag], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError("未拉取（bash scripts/pull_images.sh shopping）")
        return tag
    return _inner


def net_ping():
    sys.path.insert(0, str(REPO / "WebArena"))
    from utils.reasoningbank_llm import CompatChatClient  # noqa: E402

    client = CompatChatClient()
    text, resp = client.one_step_chat("Reply with exactly one word: OK", temperature=0.0)
    return f"回复={text.strip()!r}, tokens={resp.usage.total_tokens}"


# --------------------------------------------------------------------------- #
add(OK, "仓库", str(REPO))
check("Python / venv", venv_python)
check(".env 配置", env_file)
check("API key", key_masked)
check("依赖 import", imports)
check("本地 embedding", local_embedding, level_on_fail=WARN)
check("任务配置", task_configs)
check("Chromium", chromium)
check("Docker daemon", docker_daemon)
for tag in ["shopping_final_0712", "shopping_admin_final_0719",
            "postmill-populated-exposed-withimg", "gitlab-populated-final-port8023"]:
    check(f"镜像 {tag}", docker_image(tag), level_on_fail=WARN,
          hint="只跑 shopping 的话只需要第一个")

if "--net" in sys.argv:
    check("DeepSeek 连通", net_ping)

width = max(len(n) for _, n, _ in results) + 2
print()
for level, name, detail in results:
    print(f"{level} {name:<{width}} {detail}")
print()

if blockers:
    print(f"{len(blockers)} 个阻断项：" + "、".join(blockers))
    sys.exit(1)
print("关键项全部通过，可以起容器跑任务了。")

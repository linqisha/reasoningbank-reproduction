"""把 HuggingFace 模型直接下载成本地目录（国内走 hf-mirror，不依赖 hf_hub 的原子改名）。

为什么需要它：
* huggingface.co 在国内容易连不上；`HF_ENDPOINT=https://hf-mirror.com` 能解决大部分情况
* 某些受限环境（比如禁止重命名/删除文件的沙箱）里 `SentenceTransformer("BAAI/bge-m3")`
  在「下载完 → 重命名到 snapshots」这一步会失败；先下成本地目录再加载就能绕开

用法（仓库根目录）：

    python scripts/fetch_model.py BAAI/bge-m3 models/bge-m3
    python scripts/fetch_model.py BAAI/bge-small-en-v1.5 models/bge-small   # 130MB，先试水

然后在 .env 里用本地路径：

    RB_EMBED_PROVIDER=local
    RB_EMBED_MODEL=models/bge-m3
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

SKIP_SUFFIX = (".md", ".gitattributes", ".png", ".jpg", ".jpeg", ".gif", ".mp4")


def list_files(repo: str, endpoint: str) -> list[str]:
    url = f"{endpoint}/api/models/{repo}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        info = json.load(resp)
    return [s["rfilename"] for s in info.get("siblings", [])]


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  {dest.name}: {done/1e6:.0f}/{total/1e6:.0f} MB ({pct}%)", end="", flush=True)
    print()
    os.replace(tmp, dest)


def main() -> None:
    repo = sys.argv[1] if len(sys.argv) > 1 else "BAAI/bge-m3"
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else f"models/{repo.split('/')[-1]}")
    endpoint = (os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com").rstrip("/")
    print(f"repo={repo}\nendpoint={endpoint}\ndest={dest}")

    files = [f for f in list_files(repo, endpoint) if not f.endswith(SKIP_SUFFIX)]
    print(f"{len(files)} 个文件")
    for i, name in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {name}")
        download(f"{endpoint}/{repo}/resolve/main/{name}", dest / name)

    print(f"\n完成。在 .env 里写：RB_EMBED_PROVIDER=local\nRB_EMBED_MODEL={dest.as_posix()}")


if __name__ == "__main__":
    main()

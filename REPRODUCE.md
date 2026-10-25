# ReasoningBank 复现指南（Windows + WSL2 + 非 Google 模型）

> 对象：`C:\Users\lenovo\Downloads\reasoning-bank-main\reasoning-bank-main`（ReasoningBank，ICLR 2026）
> 已就绪副本：本目录（已打补丁，可直接用）
> 目标：把论文代码跑起来，先用 DeepSeek / 任意 OpenAI 兼容模型跑通 WebArena 的 shopping 单站，再扩到全量；SWE-bench 分支同理。

---

## 0. 先看清三件事

| # | 结论 | 依据 |
|---|---|---|
| 1 | **WebArena 必须跑在 Linux 容器里**。5 个网站（shopping / shopping_admin / reddit / gitlab / wikipedia）+ map 后端都是 Docker 镜像，浏览器自动化也依赖 Linux 环境。Windows 原生跑不通。 | `WebArena/run.sh`、`pipeline_memory.py` 全是 bash + `docker`；官方环境说明见 [webarena environment_docker](https://github.com/web-arena-x/webarena/tree/main/environment_docker) |
| 2 | **代码默认绑死 Google**：agent LLM 走 Vertex AI 的 Gemini，记忆检索的 embedding 用 `gemini-embedding-001`，且 `memory_management.py` 在 import 时就 `vertexai.init()`。换成 DeepSeek 必须改代码（已改好，见第 5 节）。 | `agents/legacy/utils/chat_api.py:92-124`、`memory_management.py:31-38`、`utils/clients.py:159` |
| 3 | **论文里的数字不要指望一次复现**：全量 812 个任务、多套 memory_mode、多次 seed，是数天 × 多卡的实验量。合理目标：先跑通 3–10 个任务的完整闭环（跑任务 → LLM 判分 → 提炼记忆 → 下一次检索到记忆），再谈规模。 | 任务分布见下表 |

任务分布（从本仓库 `config_files` 实测统计）:

| 站点 | 任务数 | 需要哪个镜像 |
|---|---|---|
| shopping | 187 | `shopping_final_0712` |
| shopping_admin | 182 | `shopping_admin_final_0719` |
| gitlab | 180 | `gitlab-populated-final-port8023` |
| map | 109 | 官方 map 后端（约 180GB，建议先跳过） |
| reddit | 106 | `postmill-populated-exposed-withimg` |
| 多站（multi） | 48 | 上面多个 |
| **合计** | **812** | 其中 128 个任务涉及 map |

---

## 1. 代码地图

```
reasoning-bank/
├── WebArena/                     ← 路线 A：网页 agent + 推理记忆（本指南主线）
│   ├── run.py                    ← 跑单个任务（browsergym + GenericAgent）
│   ├── pipeline_memory.py        ← 主流程：run → autoeval → induce_memory 循环 187/182/… 个任务
│   ├── induce_memory.py          ← 从轨迹里提炼 memory item（成功/失败各一套 prompt）
│   ├── memory_management.py      ← 记忆检索：embedding + 余弦相似度取 top-n
│   ├── autoeval/                 ← LLM-as-judge 给轨迹打对错（决定记忆是"成功经验"还是"失败教训"）
│   ├── config_files/             ← 任务定义（由 test.raw.json 生成，812 个 json）
│   ├── agents/legacy/            ← agent 本体：prompt 拼装、动作解析、token 截断
│   └── prompts/                  ← 记忆提炼 / 判分 prompt
├── SWE-Bench/                    ← 路线 B：软件工程 agent（代码在 third_party 里）
│   └── run.sh                    ← mini-extra swebench 的封装
├── third_party/
│   ├── src/minisweagent/         ← mini-swe-agent 的裁剪版 + memory/ 扩展
│   └── webarena/                 ← 打过补丁的 webarena 包（shopping 标注修正、wishlist 评测修复等）
└── pyproject.toml                ← 依赖（注意：README 说的 requirements.txt 原本不存在）
```

---

## 2. 这台机器的现状（我已核查）

| 项 | 结果 | 影响 |
|---|---|---|
| Python | `E:\Py` 3.13.13、`D:\py` 3.12.10、Anaconda 3.12.4 | 仓库要 3.13，但 **Windows 上用 3.12**（原因见坑 #3） |
| uv | 未安装 | 已下载绿色版到 `tools/uv.exe`，无需安装 |
| Docker | 未安装 | **必须装**（Docker Desktop + WSL2） |
| WSL | 有 `wsl.exe`，但 `wsl -l -v` 报 E_ACCESSDENIED | 需要管理员 PowerShell 里 `wsl --install` |
| GPU | RTX 5060 Laptop 8GB | 跑 `Qwen3-Embedding-8B`（16GB）不够；bge-m3 可以 |
| 磁盘 | C: 107GB / D: 310GB / E: 127GB 可用 | 只跑 shopping 预留 30GB；全量要 100GB+ |
| 网络 | pypi 默认走阿里云镜像可用，GitHub 可访问，curl/PowerShell 的 TLS 在沙箱内会被拦（用 Python 发请求即可） | 装依赖没问题 |
| API key | 环境变量里一个都没有 | 需要你填 `.env` |

已完成的部分（都在本目录）：

* 复制仓库 + 可用的 `.venv`（Python 3.12，177 个包，torch 2.14 / transformers 4.57 / browsergym 0.14.1）
* 补上 `requirements.txt`（原仓库缺失）和 `requirements-swe.txt`
* 生成 812 个任务配置（`WebArena/config_files/*.json`）
* 打补丁：Gemini/Vertex 依赖改为可切换 provider
* 自检通过：`python scripts/smoke_offline.py` → 3/3 通过（不花钱、不联网）

---

## 3. 你要做的四步（按顺序）

### 第 1 步：装 WSL2 + Docker Desktop（Windows，需重启 1 次）

管理员 PowerShell：

```powershell
wsl --install -d Ubuntu          # 没有 WSL 时装；已经装过就 wsl --update
wsl --set-default-version 2
```

重启后装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，在
Settings → Resources → WSL Integration 里勾上 Ubuntu。验证：

```powershell
wsl -d Ubuntu -- docker run --rm hello-world
```

> 说明：Docker 必须用 Linux 容器模式；WebArena 的镜像都是 linux/amd64，没有 Windows 版。

### 第 2 步：把代码放进 WSL 并装依赖

**不要**在 `/mnt/c/...` 下跑 Python（venv/文件锁会慢到无法接受），复制到 ext4：

```bash
# 在 WSL Ubuntu 里
cp -r /mnt/c/Users/lenovo/Documents/deepseek-harness/default-workspace/reasoning-bank ~/reasoning-bank
cd ~/reasoning-bank
cp .env.example .env        # 然后编辑 .env，见第 3 步
bash scripts/setup_wsl.sh   # uv + venv(3.12) + 依赖 + Chromium + 812 个任务配置
```

`setup_wsl.sh` 关键动作（想手动执行也可以）：

```bash
uv python install 3.12 && uv venv --python 3.12 .venv
uv pip install -r requirements.txt -r requirements-swe.txt --python .venv/bin/python
.venv/bin/python -m playwright install --with-deps chromium
cp third_party/webarena/test.raw.json WebArena/config_files/test.raw.json
(cd WebArena/config_files && ../../.venv/bin/python generate_config_files.py)
```

### 第 3 步：填 `.env`（唯一的"密钥/地址"入口）

```ini
RB_CHAT_BASE_URL=https://api.deepseek.com/v1
RB_CHAT_API_KEY=sk-...
RB_CHAT_MODEL=deepseek-chat
RB_MAX_TOKENS=8192

# embedding：默认本地跑 bge-m3（2.2GB，第一次运行自动从 hf-mirror 下载，不花钱、不用 key）
RB_EMBED_PROVIDER=local
RB_EMBED_MODEL=BAAI/bge-m3
HF_ENDPOINT=https://hf-mirror.com
# 磁盘紧张可换 BAAI/bge-large-en-v1.5（1.3GB）或 BAAI/bge-small-en-v1.5（130MB）
# 想用云端（更快、不占磁盘）就改 RB_EMBED_PROVIDER=openai + RB_EMBED_BASE_URL/KEY/MODEL

WA_SHOPPING=http://127.0.0.1:7770
WA_SHOPPING_ADMIN=http://127.0.0.1:7780/admin
WA_REDDIT=http://127.0.0.1:9999
WA_GITLAB=http://127.0.0.1:8023
```

> 如果模型下载卡住（HuggingFace 在国内时好时坏），用离线下载脚本，然后把 `.env` 指向本地目录：
>
> ```bash
> python scripts/fetch_model.py BAAI/bge-m3 models/bge-m3
> # .env: RB_EMBED_MODEL=models/bge-m3   （相对路径按仓库根目录解析）
> ```

自检（不花钱）：`.venv/bin/python scripts/smoke_offline.py`

### 第 4 步：起 shopping 容器，跑第一个任务

镜像源（选一个快的；`archive.org` 在国内通常比 Google Drive 稳）：

```bash
cd ~/images
wget http://metis.lti.cs.cmu.edu/webarena-images/shopping_final_0712.tar     # 或 archive.org 镜像
docker load --input shopping_final_0712.tar
docker run --name shopping -p 7770:80 -d shopping_final_0712
```

Magento 需要把 base_url 改成你的地址（否则页面里全是错误的链接）：

```bash
docker exec shopping /var/www/magento2/bin/magento setup:store-config:set --base-url="http://127.0.0.1:7770"
docker exec shopping mysql -u magentouser -pMyPassword magentodb \
  -e 'UPDATE core_config_data SET value="http://127.0.0.1:7770/" WHERE path = "web/secure/base_url";'
docker exec shopping /var/www/magento2/bin/magento cache:flush
```

验证：浏览器打开 `http://127.0.0.1:7770` 能看到电商首页。

然后跑单个任务（先不要记忆，确认环境通了）：

```bash
cd ~/reasoning-bank/WebArena
export PYTHONPATH="$HOME/reasoning-bank/third_party:$PYTHONPATH"
set -a; . ../.env; set +a
.venv/bin/python run.py --task_name webarena.24 --model_name deepseek-chat \
  --results_path ./results --headless true
```

产物：`results/webarena.24/`（`summary_info.json`、每步 `step_N.pkl.gz`、截图）。
（shopping 的任务 id 是 21–187 这一段里的 187 个，`webarena.21`–`webarena.25` 都是 shopping；`config_files/<id>.json` 里 `sites` 字段可确认归属。）
这是排查问题最快的入口：如果这里跑不起来，后面的 pipeline 一定跑不起来。

跑记忆闭环（3 个任务，约 10–20 分钟 + 少量 API 费用）：

```bash
bash scripts/run_webarena.sh 0 3 shopping
# 内部就是 pipeline_memory.py：run.py -> autoeval -> induce_memory.py
```

产物：

```
WebArena/results/webarena.<id>/                       轨迹 + 截图 + summary_info.json
WebArena/results/webarena.<id>/deepseek-chat_autoeval.json   LLM 判分结果
WebArena/autoeval/logs_reasoningbank_shopping/        判分日志
WebArena/memories_reasoningbank/shopping.jsonl        记忆库（逐条追加）
WebArena/memories_reasoningbank/shopping_embeddings.jsonl   检索用 embedding 缓存
```

第 2 个任务开始，`memories_reasoningbank/shopping.txt` 里会被注入检索到的记忆，
agent 的 system prompt 里会出现 "Below are some memory items that I accumulated…"。

### （可选）第 5 步：SWE-bench 分支

```bash
cd ~/reasoning-bank
export PYTHONPATH="$PWD/third_party/src:$PYTHONPATH"
export OPENAI_API_KEY="$RB_CHAT_API_KEY"          # litellm 认这两个变量
export OPENAI_API_BASE="$RB_CHAT_BASE_URL"
mkdir -p memory
.venv/bin/python -m minisweagent.run.mini_extra swebench \
  --model openai/deepseek-chat --subset lite --split test --slice 0:1 \
  --workers 1 -o ./results_swe
```

注意：

* 每个实例会 `docker pull swebench/sweb.eval.x86_64.<id>:latest`（1–2GB/个），需要 Docker 正常。
* 官方评估用 `sb-cli` 提交（需要账号），本地也可用 `swebench` 的 harness 自己跑。
* 这个分支不装 `pip install -e ./third_party` 也能用（走 `PYTHONPATH`），原因见坑 #12。

---

## 4. 三种复现深度，按成本选

| 路线 | 需要 | 时间 | 磁盘 | 能证明什么 |
|---|---|---|---|---|
| A. 离线自检（已做） | 无 | 2 分钟 | 0 | 代码能 import、记忆检索闭环逻辑正确 |
| B. shopping 单站 3–10 任务 | Docker + 1 个镜像 + API key | 半天 | ~30GB | 论文主流程真的能跑，记忆确实会被下一轮检索到 |
| C. shopping 全量 187 任务 | 同上 | 1–2 天（含 API 延迟） | ~30GB | 可对比 `memory_mode=no_memory` vs `reasoningbank` 的成功率 |
| D. 全量 812 + map | 5 个镜像 + map 后端 + 大磁盘 | 数天 | 100GB+（map 后端还要 ~180GB） | 接近论文 Table |

**建议**：先 B，确认 `no_memory` 与 `reasoningbank` 有可观测差异，再决定是否投 C/D。

---

## 5. 我改了什么（补丁清单）

| 文件 | 改动 | 为什么 |
|---|---|---|
| `requirements.txt`（新增） | 从 pyproject 生成，并补 `transformers` / `huggingface-hub` / `python-dotenv` | README 让 `pip install -r requirements.txt`，但仓库里没有这个文件；而 `chat_api.py` 顶层 `from transformers import pipeline` 没在依赖里，必报 ModuleNotFoundError |
| `WebArena/utils/reasoningbank_llm.py`（新增） | provider 层：`CompatChatClient`（任意 OpenAI 兼容 chat）+ 4 种 embedding（openai / gemini / local / hash）+ 极简 `.env` 读取 | 原代码只认 Gemini/Vertex |
| `WebArena/memory_management.py` | 删掉 import 时的 `vertexai.init()` / `genai.Client(vertexai=True)`；embedding 改为可配置；`screening()` 统一 query 与 instruction 的向量来源；缓存按维度过滤 | 无 GCP 凭据时连 `run.py` 都 import 不进去；原版两处向量可能不同维度，直接 matmul 崩 |
| `WebArena/utils/clients.py`、`autoeval/clients.py` | 新增 `OPENAI_COMPAT_Client` 与 `get_client()` | `CLIENT_DICT` 只有 gpt/gemini/claude，传 `deepseek-chat` 会 KeyError |
| `WebArena/autoeval/evaluate_trajectory.py`、`utils/evaluate_trajectory.py`、`induce_memory.py`、`pipeline_memory.py` | 去掉 `--model` 的 `choices` 白名单，默认值取 `RB_CHAT_MODEL`；改用 `get_client()` | 原来传非内置模型名直接 argparse 报错 |
| `WebArena/agents/legacy/utils/chat_api.py` | `make_chat_model()` 增加「配了 `RB_CHAT_*` 就走 OpenAI 兼容」分支；`ChatOpenAI` 用配置的 base_url；`openai/xxx` 前缀支持带 `/` 的模型名 | 原版其它名字全落到 `HuggingFaceChatModel`，而它把 base_url 写死 `http://localhost:8000/v1` |
| `WebArena/agents/legacy/utils/llm_utils.py` | `get_tokenizer()` 失败时回退 `tiktoken cl100k_base` | `count_tokens` 会对 `deepseek-chat` 调 `AutoTokenizer.from_pretrained`，去 HF 下载一个不存在的仓库 |
| `WebArena/run.py` | `--model_name` 默认取 env；`max_new_tokens` 改为 `RB_MAX_TOKENS`；`main()` 里 `makedirs` 记忆目录 | `65536` 超过 DeepSeek 单次输出上限（8192）会 400；记忆目录不存在会 FileNotFoundError |
| `WebArena/pipeline_memory.py` | 建 `memories_<mode>/` 目录；子进程用 `sys.executable` 而不是裸 `python` | 保证子进程用的是同一个 venv；目录缺失会让 run/induce 崩 |
| `third_party/README.md`、`third_party/LICENSE.md`（新增） | 补齐 pyproject 引用的两个文件 | `pip install -e ./third_party` 否则直接失败 |
| `third_party/src/minisweagent/memory/*` | 同 WebArena 的 embedding provider 改造 + `reasoningbank_llm.py` | 原版同样在 import 时要求 `GEMINI_API_KEY` |
| `third_party/src/minisweagent/run/extra/swebench.py` | judge / 记忆生成改走 `CompatChatClient`；`mkdir ./memory`；模型名里的 `/` 替换成 `_` 再拼文件路径 | 原版写死 `genai.Client()`，且 `./memory/openai/deepseek-chat.jsonl` 这种路径会崩 |
| `scripts/setup_wsl.sh`、`scripts/run_webarena.sh`、`scripts/smoke_offline.py`（新增） | 一键安装 / 一键跑 / 离线自检 | 少踩坑 |

---

## 6. 已知坑（按踩到的概率排序）

1. **README 里的 `requirements.txt` 不存在** → 用我补的那份，或直接 `uv pip install -e .`（不推荐，本项目不是标准包）。
2. **`pyproject.toml` 漏了 `transformers` / `huggingface_hub`**，但代码在顶层 import 它们 → 必装。
3. **Python 3.13 + Windows 装不上**：`browsergym 0.14.1` 锁 `playwright==1.44.0` → `greenlet==3.0.3`，该版本没有 cp313 wheel，会尝试本地编译并报 "Microsoft Visual C++ 14.0 or greater is required"。**用 3.12**（或装 VS Build Tools，不划算）。
4. **`memory_management.py` 在 import 时初始化 Vertex AI** → 没配 `GOOGLE_CLOUD_PROJECT` 时 `run.py` 直接 ImportError 级别的失败。已改为惰性 + 可配置。
5. **`memories_<mode>/` 目录不会自动创建** → `open(...,"a")` 直接 FileNotFoundError。已在 run/pipeline 里补 `makedirs`。
6. **第一次 `select_memory` 必然返回空**（缓存里还没有历史），所以第 1 个任务是"无记忆"跑，第 2 个任务才会注入记忆 —— 这不是 bug。
7. **换 embedding 模型后必须删缓存**：维度不一致会在 `matmul` 处炸。现在会跳过不匹配的行并告警，但最好直接删 `*_embeddings.jsonl` 重来。
8. **`run.sh` 里写死了作者的家目录和项目 ID**（`/home/junyann_google_com/...`、`zifengw-research`）→ 别直接用，用 `scripts/run_webarena.sh`。
9. **端口要一致**：作者用的是 8082/8020/8030/8040/8060，官方镜像是 7770/7780/9999/8023/8888。`WA_*` 改了必须**重新生成** `config_files`（`generate_config_files.py` 会把地址烧进 json）。
10. **server 端 base_url 必须改**（Magento 的 `web/secure/base_url`、GitLab 的 `external_url`），否则页面内链接指向 `localhost:80`，agent 会一直"找不到页面"。
11. **Windows 沙箱里跑不了 Playwright**（命名管道被拦，报 `spawn EPERM` / `CreateFile WinError 5`）。这是本会话的限制，不是代码问题；在 WSL 里正常。
12. **`pip install -e ./third_party` 会失败**：原快照缺 `README.md`/`LICENSE.md`（已补）；另外某些沙箱环境禁止删除工作区文件，editable 构建写 egg-info 时会 PermissionError。用 `PYTHONPATH=third_party/src` 最省事。
13. **`SELECT_MEMORY` 的 `prefer_model="gemini"` 是历史参数**，现在不起作用，别被误导。
14. **`Swe-bench` 的 `SWE-Bench/run.sh` 里 `--output` 是错的**，mini-extra 的选项是 `-o/--output`；且 `GOOGLE_*` 留空会走默认。
15. **本地 embedding 的模型下载可能失败**（HuggingFace 连不上，或环境禁止原子改名）：用 `python scripts/fetch_model.py <repo> <dir>` 直接下到本地目录，再让 `RB_EMBED_MODEL` 指向它；`HF_ENDPOINT=https://hf-mirror.com` 必须**在进程启动前**生效（`.env` 里写就行，代码 import 时就会读）。
16. **换 embedding 模型 = 换向量空间**：`bge-m3`(1024 维) 与 `gemini-embedding-001`(3072 维) 不能混用同一份缓存，换之前删掉 `memories_*/**_embeddings.jsonl`。
17. **`HF_ENDPOINT` / `HF_HOME` 要在 import transformers 之前设置**，否则不生效——`reasoningbank_llm` 在 import 阶段就加载 `.env` 来保证这一点。

---

## 7. 费用 / 时间怎么估

单任务 token 量 ≈ `步数(≤30) × (axtree 提示 ~3–8k tokens + 历史动作)`，加上 autoeval 与记忆提炼各 1 次调用（各 ~5–15k tokens）。

粗略公式（shopping，`max_steps=30`）：

```
输入 tokens/任务 ≈ 30 × 6k ≈ 180k
输出 tokens/任务 ≈ 30 × 0.3k ≈ 9k
每任务调用次数 ≈ 30(agent) + 1(judge) + 1(记忆) ≈ 32
```

按 DeepSeek 当前价格换算即可（价格会变，别照抄旧数字）；187 个任务的成本大致在"几美元到十几美元"量级，主要变量是页面 axtree 长度和步数。embedding 费用可忽略（每任务 1–2 次短文本）。

时间：单任务 1–3 分钟（含 30 步浏览器交互 + LLM 延迟），187 个任务串行约 6–10 小时；开 3–4 并发要注意 WebArena 站点的状态会被不同任务互相污染（原版也是串行跑的）。

---

## 8. 我实际验证过的（可复现）

```
$ .venv\Scripts\python.exe scripts\smoke_offline.py
[ok]   任务配置 — 812 个任务
[ok]   模块 import + 模型配置 — chat=deepseek-chat judge=deepseek-chat base_url=openai-default embed_provider=hash
[ok]   记忆检索闭环 — 召回 task_id=1
自检通过

# 本地 embedding（用 bge-small 跑通同样的代码路径；bge-m3 只是把模型换大）
load 9.0s -> LocalEmbedder(dim=384), 2 条文本 22ms, 向量已归一化
三条候选记忆里，"put this product into my wishlist" 正确召回 task 2（wishlist）而不是 task 1（红鞋）

$ python -m minisweagent.run.mini_extra            # SWE-bench 分支 CLI
  config / inspect / github-issue / swebench / swebench-single
$ python -m minisweagent.run.mini_extra swebench --help   # 正常
```

未验证（缺条件，不是代码问题）：真实 API 调用（没有 key）、Docker 镜像（没装 Docker）、Playwright 实跑（Windows 沙箱限制）。

---

## 9. 你的下一步（三选一）

1. **先跑通最小闭环**：按第 3 节做完，把 `bash scripts/run_webarena.sh 0 3 shopping` 的报错贴回来，我按报错改。
2. **只要 SWE-bench**：装 Docker 后按第 3 节第 5 步跑 1 个 lite 实例。
3. **先不装 Docker**：我可以把 `run.py` 的 `openended` 模式指向一个公网页面，在 WSL 里验证 agent + 记忆注入 + 判分链路（不含 WebArena 标准评分）。

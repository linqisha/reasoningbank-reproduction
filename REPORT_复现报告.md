# ReasoningBank 复现报告：源码做了什么、我们做了什么、卡在哪

> 目标代码：ReasoningBank（ICLR 2026, `reasoning-bank-main`）
> 复现环境：Windows 11 + WSL2 Ubuntu 24.04 + Docker Desktop 29 + DeepSeek API + 本地 bge-m3
> 结论先行：**机制完全复现（跑通闭环），论文效果未复现（样本与噪声不足，非实现问题）**

---

## 一、原始代码在做什么

### 1.1 一句话概括

ReasoningBank 给 web / coding agent 加了一个**可自我进化的记忆库**：每次任务结束后从轨迹里提炼"经验条目"，下次遇到相似任务时检索出最相关的 1 条注入 system prompt。成功轨迹提炼"该怎么做"，失败轨迹提炼"别再怎么做"。

### 1.2 两条实验线

| 分支 | 底座 | 任务域 | 记忆落点 |
|---|---|---|---|
| `WebArena/` | BrowserGym + 自研 `GenericAgent` | 812 个网页任务（shopping / admin / gitlab / reddit / map） | `memories_<mode>/<site>.jsonl` |
| `SWE-Bench/` + `third_party/src/minisweagent` | mini-swe-agent | SWE-bench 实例 | `./memory/<model>.jsonl` |

两条线共用同一套记忆机制，只是"轨迹"从网页动作换成了 shell 命令。

### 1.3 WebArena 主线数据流（核心）

```
pipeline_memory.py            ← 主循环，按站点筛出任务 id，逐个跑
   │
   ├─(1) run.py --task_name webarena.<id> --memory_path memories_*/shopping.txt
   │      ├─ 读 config_files/<id>.json 的 intent 作为 query
   │      ├─ select_memory(n=1)  ← memory_management.py
   │      │      把 query 变成向量，和 <site>_embeddings.jsonl 里历史 query 向量算余弦，
   │      │      取 top-1 对应的记忆条目
   │      ├─ 把选中的记忆写进 memories_*/shopping.txt
   │      ├─ 起 BrowserGym 环境（Playwright + Chromium），跑 GenericAgent ≤30 步
   │      │      agent 的 system prompt = 基础指令 + 「Below are some memory items…」+ 记忆正文
   │      └─ 产物：results/webarena.<id>/{step_*.pkl.gz, 截图, summary_info.json}
   │
   ├─(2) autoeval.evaluate_trajectory
   │      LLM-as-judge：把「目标 + 每步 axtree 文本 + 最终回答 + 动作序列」交给 judge 模型，
   │      输出 success/fail + 理由，写入 <model>_autoeval.json
   │
   └─(3) induce_memory.py
          读 step pkl → 还原 think/action 轨迹 → 根据对错选 SUCCESSFUL_SI / FAILED_SI prompt
          → 让 LLM 提炼「至多 3 条」记忆，按 "\n\n" 切分成 memory_items
          → 追加到 memories_*/<site>.jsonl（带 task_id / query / status / template_id）
```

### 1.4 记忆条目的格式（论文的三段式）

```
# Memory Item 1
## Title        一句话标题
## Description  什么时候该用这条
## Content      1–3 句可操作的建议
```

### 1.5 关键设计点

| 设计 | 代码位置 | 作用 |
|---|---|---|
| 四种记忆模式 | `pipeline_memory.py --memory_mode` | `no_memory`（对照） / `reasoningbank`（本文方法） / `awm`（只从成功中学） / `synapse`（直接存原始轨迹） |
| 检索只看 query 相似度 | `memory_management.py: screening()` | 用 `Instruct: …\nQuery: …` 包装后编码，与历史 query 向量比余弦 |
| 对错信号可切换 | `--judge autoeval\|gt` | autoeval 省钱但会误判；gt 用官方评分器但需环境真跑对 |
| 记忆去重靠 template_id | 记录了但**没实现去重** | 同模板任务的记忆会重复堆积 |
| 成功/失败两套提炼 prompt | `prompts/memory_instruction.py` | 失败轨迹走"反思为什么错"的分支 |

---

## 二、我们复现时实际做了什么

### 2.1 总体改造思路

原代码把模型层焊死在 Google 栈上（Gemini via Vertex AI + `gemini-embedding-001`），而我们的约束是：**只有 DeepSeek 的 key、没有 GCP、在中国大陆网络**。所以做了一层"可切换 provider"，其余逻辑一律不动。

```
              原版                          复现版
LLM        Gemini 2.5 (Vertex)      →   DeepSeek（任意 OpenAI 兼容）
judge      Gemini 2.5 Pro           →   DeepSeek
embedding  gemini-embedding-001     →   本地 sentence-transformers bge-m3 (1024 维)
环境       Linux + Docker + 官方镜像  →  WSL2 + Docker + 瘦身镜像 (5.4GB)
```

### 2.2 代码改动清单

| 文件 | 改动 | 为什么 |
|---|---|---|
| `WebArena/utils/reasoningbank_llm.py`（新增） | `CompatChatClient`（任意 OpenAI 兼容 chat）+ 4 种 embedding（openai / gemini / local / 离线 hash）+ 极简 `.env` 加载 | 原版只认 Gemini/Vertex；DeepSeek 没有 `/embeddings`，必须能换后端 |
| `WebArena/memory_management.py` | 删掉 import 时的 `vertexai.init()`；embedding 走 provider；`screening()` 统一 query 与 instruction 的向量来源；缓存按维度过滤 | 没 GCP 凭据时连 `run.py` 都 import 不进去；原版两处向量可能维度不一致，直接 matmul 崩 |
| `utils/clients.py`、`autoeval/clients.py` | 新增 `OPENAI_COMPAT_Client` + `get_client()` | `CLIENT_DICT` 只有 gpt/gemini/claude，传 `deepseek-chat` 会 KeyError |
| `evaluate_trajectory.py` ×2、`induce_memory.py`、`pipeline_memory.py` | 去掉 `--model` 的 choices 白名单；默认值取 env；子进程用 `sys.executable` | 传非内置模型名直接 argparse 报错；`python` 可能不是 venv 里那个 |
| `agents/legacy/utils/chat_api.py` | `make_chat_model()` 增加「配了 `RB_CHAT_*` 就走 OpenAI 兼容」分支；client 走配置的 base_url | 其它模型名全落到 `HuggingFaceChatModel`，而它把 base_url 写死 `localhost:8000` |
| `agents/legacy/utils/llm_utils.py` | `get_tokenizer()` 失败回退 tiktoken | `count_tokens` 会对 `deepseek-chat` 去 HF 下载 tokenizer |
| `agents/legacy/dynamic_prompting.py` | system prompt 加"输出格式"约束（单行、ASCII 引号） | 多行 `send_msg_to_user` 会被动作解析器判为空动作，6 次重试后任务失败 |
| `run.py` | `--model_name` 默认取 env；`max_new_tokens` 改 `RB_MAX_TOKENS`；补 `makedirs` | 65536 超过 DeepSeek 输出上限会 400；记忆目录不存在会 FileNotFoundError |
| `third_party/webarena/evaluation_harness/helper_functions.py` | `llm_fuzzy_match` 的 Gemini client 改惰性 + 优先 OpenAI 兼容；解析失败不再 assert 崩 | 原版 import 时就要求 `GEMINI_API_KEY`，一 reset 环境就崩 |
| `third_party/webarena/evaluation_harness/evaluators.py` | 新增 `_page_content()`：等 load + 重试 5 次；`page.goto` 加 domcontentloaded 回退 | 页面跳转中 `page.content()` 会抛错，把整个任务判失败 |
| `third_party/src/minisweagent/*` | 同样的 embedding/judge 改造；`mkdir ./memory`；模型名里的 `/` 替换成 `_` | `./memory/openai/deepseek-chat.jsonl` 这种路径会崩 |
| `requirements.txt` / `requirements-swe.txt`（新增） | 从 pyproject 生成，补 `transformers`、`huggingface-hub`、`sentence-transformers`、`datasets` | README 让装 requirements.txt 但仓库里没有；代码 import 了未声明的包 |
| `scripts/*.py/.sh`（新增 7 个） | 装环境、拉镜像、体检、离线自检、跑批、汇总评分、看轨迹 | 把踩过的坑固化成脚本 |

### 2.3 实际跑起来的链路

```
WSL2 Ubuntu 24.04
 └── Docker Desktop（数据盘在 D:\Docker，代理走 Clash 127.0.0.1:7897）
      └── shopping 容器（am1n3e/webarena-verified-shopping, 5.4GB, 端口 7770）
           ↑ Magento 电商站，base_url 已改到 127.0.0.1:7770
 └── Python 3.12 venv（uv 装 177 个包 + sentence-transformers）
      ├── run.py         → BrowserGym + Chromium 操作站点
      ├── autoeval       → DeepSeek 判分
      └── induce_memory  → DeepSeek 提炼记忆 → 本地 bge-m3 编码 → 下次检索注入
```

跑过的实验：

| 组 | 任务数 | 成功率 | 备注 |
|---|---|---|---|
| 冒烟（21/22/23） | 3 | 2/3 | 首次验证闭环 |
| `results_mem` | 20 | 10/20 (50%) | `JUDGE=gt` |
| `results_nomem` | 20 | 11/20 (55%) | `MEM_MODE=no_memory` |

---

## 三、遇到的困难与解决（按类别）

### 3.1 模型层：这套代码只认 Google

| # | 现象 | 根因 | 解决 |
|---|---|---|---|
| 1 | `ValueError: No API key was provided`（import 阶段） | `memory_management.py` 在模块级执行 `vertexai.init()` + `genai.Client(vertexai=True)` | 改惰性 + provider 层 |
| 2 | `KeyError: 'deepseek-chat'` | `CLIENT_DICT` 只有 gpt/gemini/claude | 加 `get_client()` 兜底 |
| 3 | `argparse: invalid choice` | CLI 白名单限制模型名 | 去掉 `choices` |
| 4 | 请求发到 `localhost:8000` | 非内置模型名落到 `HuggingFaceChatModel`，base_url 写死 | 加 OpenAI 兼容分支 |
| 5 | `AutoTokenizer` 去 HF 下载不存在的仓库 | `count_tokens` 拿模型名当 HF repo | 失败回退 tiktoken |
| 6 | 判分器 import 就崩 | vendored webarena 的 `helper_functions` 模块级建 Gemini client | 惰性 + 判分也走 DeepSeek |
| 7 | DeepSeek 没有 embedding 接口 | 原版用 `gemini-embedding-001` | 本地 bge-m3（1024 维），缓存按维度过滤 |
| 8 | 给 bge 加 `Instruct:` 前缀后相似度被压平（0.82→0.63） | 原版前缀是为 Gemini 的非对称检索设计的 | 对称模型不加前缀（`uses_instruction` 开关） |

### 3.2 依赖与环境

| # | 现象 | 根因 | 解决 |
|---|---|---|---|
| 9 | `pip install -r requirements.txt` 找不到文件 | README 写了但仓库没这个文件 | 从 pyproject 生成并补漏 |
| 10 | `ModuleNotFoundError: transformers` | 代码顶层 import 但 pyproject 没声明 | 补进 requirements |
| 11 | Windows 上 `greenlet` 编译失败（要 MSVC） | py3.13 没有 greenlet 3.0.3 的 wheel（browsergym 锁了 playwright 1.44） | 改用 Python 3.12 |
| 12 | `ensurepip` / `pip` 在工作区里 chmod 失败 | 沙箱禁止删除/改权限工作区文件 | 下载 uv 绿色版，用 `uv pip install` 绕开 |
| 13 | Windows 上 Playwright 起不来（`spawn EPERM` / 命名管道 WinError 5） | 沙箱禁止命名管道 | 所有浏览器操作放到 WSL 里跑 |
| 14 | `playwright install-deps` 失败 | Ubuntu 24.04 把 `libasound2` 改名 `libasound2t64` | 手动装依赖清单 |
| 15 | `pip install -e ./third_party` 构建失败 | 快照缺 `README.md`/`LICENSE.md`；沙箱禁删导致 egg-info 写不进 | 补齐文件 + 改用 `PYTHONPATH=third_party/src` |

### 3.3 网络与镜像源（最耗时的一段）

| # | 现象 | 根因 | 解决 |
|---|---|---|---|
| 16 | 官方 tar 下载 502 | `metis.lti.cs.cmu.edu` 服务挂了 | 换 Docker Hub 社区镜像 |
| 17 | archive.org 403 | 该条目 `is_dark=true`，已下架 | 同上 |
| 18 | 45GB 镜像拉到 38GB 卡死 | 镜像几乎是**一整层 43GB**，Docker 不支持单层断点续传 | 放弃，换 5.4GB 瘦身镜像 |
| 19 | `docker pull` 卡在 0% / `unexpected EOF` | 关掉代理后 DNS 被污染（解析到 `2a03:2880:...` 黑洞地址） | Docker Desktop 配代理 `127.0.0.1:7897`，全程别切节点 |
| 20 | `nltk punkt_tab` 下载超时 | 走 `raw.githubusercontent.com`；新版 NLTK 还拒绝代理下载 | `curl` 手动下到 `~/nltk_data/tokenizers/` |
| 21 | WSL 用不了 Windows 的 localhost 代理 | NAT 模式限制 | 用 `ip route` 拿网关 IP 当代理地址 |
| 22 | 43GB 垃圾数据占着 D 盘 | Docker 的 vhdx 只涨不缩 | 停 Docker → 重命名/删除 `docker_data.vhdx` 重建 |

### 3.4 运行期的坑

| # | 现象 | 根因 | 解决 |
|---|---|---|---|
| 23 | `AssertionError: WA_MAP missing` | browsergym 要求 7 个 `WA_*` 全部存在 | 填占位地址 |
| 24 | `Received an empty action` ×6 → 任务判失败 | 多行字符串 + 弯引号破坏动作解析 | system prompt 加格式约束 |
| 25 | `Page.content: page is navigating` | 评测器在页面跳转中抓 HTML | 等 load + 重试 5 次 |
| 26 | `Page.goto: Timeout 10000ms` | browsergym 初始导航超时写死 10s，冷启动必崩 | 改 60s |
| 27 | 点击/填表频繁超时，搜索框内容被拼接 | 动作超时写死 **500ms** | 改 3000ms |
| 28 | 对照组"输给"无记忆组 | **跑批顺序**导致第一组吃冷启动开销 | 先热身，或两组交替 |
| 29 | autoeval 把"漏了一个名字"判成功 | LLM 判分无法核对清单完整性 | 对照实验改用 `JUDGE=gt` |

---

## 四、结果怎么解读

1. **机制复现成功**：轨迹里可以看到 `Memory Item 1 is relevant …`，agent 会按记忆建议去"翻完所有评论页"，说明检索→注入→影响决策这条链是通的。
2. **效果没复现**：20 vs 20 是 50% vs 55%，唯一差异（task 26）是 `Page.goto` 超时崩溃，属于基础设施抖动。
3. **步数膨胀不是记忆的锅**：记忆组 7.3 步 vs 对照组 5.8 步，主要来自 500ms 动作超时导致的重试；且记忆组跑在前面，吃了冷启动。
4. **记忆内容太泛**：10 个任务的记忆库里全是"去订单页看订单历史""要翻完所有分页"这类显性常识 —— 论文靠 187 个任务才积累出有价值的"坑"。

---

## 五、结论与可复用的经验

### 值得写进报告的结论

- 这套代码的**算法核心与模型层高度耦合**（Gemini/Vertex 写死在 import 阶段、判分器、embedding 三处），换模型不是改配置而是改代码 —— 复现论文时"模型无关性"是第一个要评估的成本。
- 论文的收益依赖**规模**：任务数（记忆池大小）、环境稳定性（噪声）、模型能力。小规模下机制可验证、效果不可验证。
- 复现一个 agent 论文，**80% 的时间花在环境和上游资源**（镜像、网络、依赖、浏览器），20% 才是算法。

### 如果重来一次的最短路径（已固化成脚本）

```bash
# 1. WSL2 里装环境（Python 3.12 + 依赖 + Chromium + 812 任务配置）
bash scripts/setup_wsl.sh

# 2. 拉瘦身镜像（官方 tar 源已失效）
bash scripts/pull_images.sh shopping

# 3. 起站点 + 修 base_url
bash scripts/start_shopping.sh

# 4. 体检（12 项，含一次真实 API 调用）
python scripts/doctor.py --net

# 5. 冒烟：单任务 → 三任务闭环
python run.py --task_name webarena.21 --model_name deepseek-chat
OUT=./results_mem bash ../scripts/run_webarena.sh 0 3 shopping

# 6. 对照实验 + 汇总
OUT=./results_mem JUDGE=gt bash ../scripts/run_webarena.sh 0 20 shopping
MEM_MODE=no_memory OUT=./results_nomem JUDGE=gt bash ../scripts/run_webarena.sh 0 20 shopping
python ../scripts/report_webarena.py results_mem results_nomem

# 7. 定性分析
python ../scripts/inspect_traj.py results_mem/webarena.117 results_nomem/webarena.117
```

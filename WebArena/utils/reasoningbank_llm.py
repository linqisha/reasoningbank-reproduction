"""ReasoningBank 的模型/向量层：把仓库里写死的 Gemini + Vertex AI 换成可配置的 provider。

原仓库的三处硬编码
------------------
1. ``agents/legacy/utils/chat_api.py``
   ``ChatGemini`` 固定 ``genai.Client(vertexai=True)``；其它名字全部落到
   ``HuggingFaceChatModel``，而后者把 base_url 写死成 ``http://localhost:8000/v1``。
2. ``memory_management.py``
   模块 import 时就执行 ``vertexai.init(...)``，embedding 只走 ``gemini-embedding-001``。
3. ``utils/clients.py`` / ``autoeval/clients.py``
   ``CLIENT_DICT`` 只有 gpt / gemini / claude 三类，接第三方模型会 ``KeyError``。

本模块给出一层薄封装：
* :class:`CompatChatClient`   任意 OpenAI 兼容 ``/chat/completions``（DeepSeek、通义、Kimi、
  SiliconFlow、one-api、本地 vLLM / Ollama 均可）
* :func:`get_embedder`        可切换 embedding：OpenAI 兼容 / Gemini / 本地 sentence-transformers /
  离线 hash（仅用于无网无 key 的流程冒烟）
* :func:`load_dotenv_if_present`  极简 .env 读取，省得手动 export

环境变量（建议写在仓库根目录或 ``WebArena/`` 下的 ``.env``）
----------------------------------------------------------
::

    RB_CHAT_BASE_URL=https://api.deepseek.com/v1
    RB_CHAT_API_KEY=sk-xxx
    RB_CHAT_MODEL=deepseek-chat
    RB_JUDGE_MODEL=deepseek-chat          # 可选，默认跟 RB_CHAT_MODEL 一致
    RB_MAX_TOKENS=8192                    # DeepSeek 单次输出上限就是 8k

    RB_EMBED_PROVIDER=auto                # auto | openai | gemini | local | hash
    RB_EMBED_BASE_URL=                    # 留空则复用 RB_CHAT_BASE_URL
    RB_EMBED_API_KEY=                     # 留空则复用 RB_CHAT_API_KEY
    RB_EMBED_MODEL=                       # 例如 text-embedding-3-small / BAAI/bge-m3 / bge-small-zh-v1.5

注意：DeepSeek 官方 API **没有** ``/embeddings`` 接口，embedding 需要另找一家
（SiliconFlow 的 ``BAAI/bge-m3``、阿里 DashScope 的 ``text-embedding-v4``，或者用
``RB_EMBED_PROVIDER=local`` 在本地跑 sentence-transformers）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 极简 .env 支持（不引入 python-dotenv 依赖）
# --------------------------------------------------------------------------- #

_DOTENV_LOADED = False


def _candidate_dotenv_paths() -> List[Path]:
    here = Path(__file__).resolve()
    # WebArena/utils/reasoningbank_llm.py -> WebArena -> 仓库根
    roots = [here.parents[1], here.parents[2]] if len(here.parents) > 2 else [here.parent]
    return [p / ".env" for p in roots]


def load_dotenv_if_present(force: bool = False) -> None:
    """读取 .env（KEY=VALUE），已存在的环境变量优先，不覆盖。"""
    global _DOTENV_LOADED
    if _DOTENV_LOADED and not force:
        return
    _DOTENV_LOADED = True
    for path in _candidate_dotenv_paths():
        try:
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            logger.info("loaded env file: %s", path)
        except Exception as exc:  # pragma: no cover - 环境问题不应阻断主流程
            logger.warning("failed to read %s: %s", path, exc)


def _env(*names: str, default: Optional[str] = None) -> Optional[str]:
    load_dotenv_if_present()
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


# --------------------------------------------------------------------------- #
# Chat：任意 OpenAI 兼容接口
# --------------------------------------------------------------------------- #


def chat_base_url() -> Optional[str]:
    return _env("RB_CHAT_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE")


def chat_api_key() -> Optional[str]:
    return _env("RB_CHAT_API_KEY", "OPENAI_API_KEY")


def chat_model_name(default: str = "deepseek-chat") -> str:
    return _env("RB_CHAT_MODEL", "RB_MODEL", default=default)


def judge_model_name() -> str:
    return _env("RB_JUDGE_MODEL", default=chat_model_name())


def max_output_tokens(default: int = 8192) -> int:
    try:
        return int(_env("RB_MAX_TOKENS", default=str(default)))
    except (TypeError, ValueError):
        return default


class CompatChatClient:
    """OpenAI 兼容 chat 客户端，接口对齐仓库里的 ``CLIENT_DICT`` 各项。

    提供 ``chat(messages, ...)`` 与 ``one_step_chat(text, system_msg=..., ...)``，
    返回值同样是 ``(text, raw_response)``。
    """

    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.0) -> None:
        from openai import OpenAI  # 延迟 import，避免没装 openai 时整包不可用

        base_url = chat_base_url()
        api_key = chat_api_key()
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        # 本地 vLLM / Ollama 常常不校验 key，但 openai SDK 必须拿到一个非空值；
        # 云端 provider 没有真 key 时会直接 401，报错也够清楚。
        kwargs["api_key"] = api_key or "EMPTY"
        if not base_url and not api_key:
            logger.warning(
                "既没有 RB_CHAT_BASE_URL 也没有 RB_CHAT_API_KEY，将回退到 OpenAI 官方默认地址"
            )

        self.model_name = model_name or chat_model_name()
        self.temperature_default = temperature
        self.max_tokens = max_output_tokens()
        self._client = OpenAI(**kwargs)
        logger.info(
            "CompatChatClient: model=%s base_url=%s max_tokens=%s",
            self.model_name,
            base_url or "https://api.openai.com/v1",
            self.max_tokens,
        )

    # -- 与仓库内 client 对齐的接口 ----------------------------------------- #
    def chat(self, messages, temperature: Optional[float] = None, json_mode: bool = False):
        temperature = self.temperature_default if temperature is None else temperature
        request = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        if self.max_tokens:
            request["max_tokens"] = self.max_tokens

        try:
            response = self._client.chat.completions.create(**request)
        except Exception as exc:  # 不同 provider 对 max_tokens 的上限不一致
            text = str(exc).lower()
            if "max_tokens" in text and "max_tokens" in request:
                logger.warning("provider rejected max_tokens=%s, retrying without it", self.max_tokens)
                request.pop("max_tokens", None)
                response = self._client.chat.completions.create(**request)
            else:
                raise

        content = response.choices[0].message.content or ""
        return content, response

    def one_step_chat(self, text, system_msg: Optional[str] = None, json_mode: bool = False,
                      temperature: Optional[float] = None):
        messages = []
        if system_msg is not None:
            messages.append({"role": "system", "content": system_msg})
        messages.append({"role": "user", "content": text})
        return self.chat(messages, temperature=temperature, json_mode=json_mode)


# --------------------------------------------------------------------------- #
# Embedding
# --------------------------------------------------------------------------- #


def _l2_normalize_rows(vectors: Sequence[Sequence[float]]) -> List[List[float]]:
    import math

    out = []
    for vec in vectors:
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


class BaseEmbedder:
    name = "base"
    dim: Optional[int] = None
    #: 是否适合「query 侧加 "Instruct: ..." 前缀」的非对称检索。
    #: Gemini 的 task_type=RETRIEVAL_QUERY/DOCUMENT 就是这种设计；
    #: bge / OpenAI embedding 是对称的，加了前缀反而会把相似度差距压平（实测 0.82→0.63）。
    uses_instruction = False

    def embed(self, texts: Sequence[str], task_type: str = "document") -> List[List[float]]:
        raise NotImplementedError

    def embed_one(self, text: str, task_type: str = "query") -> List[float]:
        return self.embed([text], task_type=task_type)[0]

    def __repr__(self) -> str:  # pragma: no cover - 仅用于日志
        return f"{type(self).__name__}(name={self.name}, dim={self.dim})"


class OpenAICompatEmbedder(BaseEmbedder):
    """任意 OpenAI 兼容 ``/embeddings``（SiliconFlow、DashScope 兼容模式、OpenAI、Jina…）。"""

    def __init__(self, model: str, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 batch_size: int = 16) -> None:
        from openai import OpenAI

        self.name = model
        self.batch_size = batch_size
        kwargs = {}
        base_url = base_url or _env("RB_EMBED_BASE_URL") or chat_base_url()
        api_key = api_key or _env("RB_EMBED_API_KEY") or chat_api_key()
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        self._client = OpenAI(**kwargs)
        self._task_type = None
        logger.info("OpenAICompatEmbedder: model=%s base_url=%s", model, base_url)

    def embed(self, texts: Sequence[str], task_type: str = "document") -> List[List[float]]:
        vectors: List[List[float]] = []
        texts = list(texts)
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = self._client.embeddings.create(model=self.name, input=batch)
            vectors.extend([item.embedding for item in response.data])
        if vectors:
            self.dim = len(vectors[0])
        return vectors


class GeminiEmbedder(BaseEmbedder):
    """Google Gemini embedding；有 GEMINI_API_KEY 走 API，否则尝试 Vertex AI。"""

    uses_instruction = True

    def __init__(self, model: str = "gemini-embedding-001", dimensionality: int = 3072) -> None:
        from google import genai

        self.name = model
        self.dimensionality = dimensionality
        api_key = _env("GEMINI_API_KEY", "GOOGLE_API_KEY")
        if api_key:
            self._client = genai.Client(api_key=api_key)
            self._vertexai = False
        else:
            # 沿用仓库原来的 Vertex AI 用法；需要 GOOGLE_CLOUD_PROJECT + ADC
            self._client = genai.Client(vertexai=True)
            self._vertexai = True
        logger.info("GeminiEmbedder: model=%s vertexai=%s", model, self._vertexai)

    def embed(self, texts: Sequence[str], task_type: str = "document") -> List[List[float]]:
        from google.genai.types import EmbedContentConfig

        task = "RETRIEVAL_DOCUMENT" if task_type == "document" else "RETRIEVAL_QUERY"
        response = self._client.models.embed_content(
            model=self.name,
            contents=list(texts),
            config=EmbedContentConfig(
                task_type=task,
                output_dimensionality=self.dimensionality,
                title="Memory Embeddings" if task_type == "document" else None,
            ),
        )
        vectors = [item.values if hasattr(item, "values") else item.embedding for item in response.embeddings]
        if vectors:
            self.dim = len(vectors[0])
        return vectors


class LocalEmbedder(BaseEmbedder):
    """本地 sentence-transformers（CPU/GPU 都行，8GB 显卡跑 bge-m3 / bge-large 足够）。"""

    def __init__(self, model: str) -> None:
        from sentence_transformers import SentenceTransformer

        model = _resolve_local_model_path(model)
        self.name = model
        self._model = SentenceTransformer(model)
        if hasattr(self._model, "get_embedding_dimension"):  # sentence-transformers >= 5
            self.dim = self._model.get_embedding_dimension()
        else:  # pragma: no cover - 老版本
            self.dim = self._model.get_sentence_embedding_dimension()
        logger.info("LocalEmbedder: model=%s dim=%s", model, self.dim)

    def embed(self, texts: Sequence[str], task_type: str = "document") -> List[List[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, vec)) for vec in vectors]


class HashEmbedder(BaseEmbedder):
    """离线兜底：token 哈希装袋向量。

    只用来在**没有网络/没有 key** 时验证「检索→注入→评测→写回记忆」这条链路是否通，
    检索质量完全不能代表真实 embedding，请不要用它跑实验结论。
    """

    _token_re = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")

    def __init__(self, dim: int = 512) -> None:
        self.name = "hash-bow"
        self.dim = dim
        logger.warning("使用 HashEmbedder（离线冒烟用），检索质量不代表真实实验结果")

    def embed(self, texts: Sequence[str], task_type: str = "document") -> List[List[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in self._token_re.findall(text.lower()):
                digest = hashlib.md5(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vec[index] += sign
            vectors.append(vec)
        return _l2_normalize_rows(vectors)


_EMBEDDER: Optional[BaseEmbedder] = None


def _resolve_local_model_path(model: str) -> str:
    """把 ``models/bge-m3`` 这类相对路径解析成仓库根目录下的路径。

    WebArena 的脚本是在 ``WebArena/`` 里跑的，直接传相对路径会被当成
    ``WebArena/models/...``；这里统一按仓库根目录解析，避免"换个目录就找不到模型"。
    """
    path = Path(model)
    if path.is_absolute() or path.exists():
        return str(path)
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / path
    if candidate.exists():
        return str(candidate)
    return model  # 都不是，就当作 HF repo id 交给 sentence-transformers 去下载


def _summarize_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def get_embedder(force_provider: Optional[str] = None, verbose: bool = True) -> BaseEmbedder:
    """按 ``RB_EMBED_PROVIDER`` 返回 embedding 后端（进程内缓存）。"""
    global _EMBEDDER
    if _EMBEDDER is not None and force_provider is None:
        return _EMBEDDER

    load_dotenv_if_present()
    provider = (force_provider or _env("RB_EMBED_PROVIDER", default="auto") or "auto").lower()
    model = _env("RB_EMBED_MODEL")

    embedder: Optional[BaseEmbedder] = None

    def try_build(name: str, factory) -> Optional[BaseEmbedder]:
        try:
            return factory()
        except Exception as exc:
            if verbose:
                logger.warning("embedding provider %s 不可用（%s）", name, _summarize_error(exc))
            return None

    if provider in ("openai", "auto") and model:
        embedder = try_build("openai", lambda: OpenAICompatEmbedder(model))
        if embedder is None and provider == "openai":
            raise RuntimeError("RB_EMBED_PROVIDER=openai 但构造失败，请检查 RB_EMBED_BASE_URL / RB_EMBED_MODEL")

    if embedder is None and provider in ("gemini", "auto") and _env("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        embedder = try_build("gemini", lambda: GeminiEmbedder(model or "gemini-embedding-001"))

    if embedder is None and provider in ("local", "auto") and model:
        embedder = try_build("local", lambda: LocalEmbedder(model))

    if embedder is None:
        if provider not in ("hash", "auto"):
            raise RuntimeError(f"无法构造 embedding 后端：provider={provider} model={model}")
        embedder = HashEmbedder()

    if verbose:
        logger.info("embedding backend: %r", embedder)
    _EMBEDDER = embedder
    return embedder


def reset_embedder() -> None:
    """主要给测试用：清掉缓存，下次重新读环境变量。"""
    global _EMBEDDER
    _EMBEDDER = None


def describe() -> str:
    """一行摘要，方便在日志开头确认这次到底用了什么模型。"""
    load_dotenv_if_present()
    return (
        f"chat={chat_model_name()} judge={judge_model_name()} "
        f"base_url={chat_base_url() or 'openai-default'} "
        f"embed_provider={_env('RB_EMBED_PROVIDER', default='auto')} "
        f"embed_model={_env('RB_EMBED_MODEL') or '-'}"
    )


# 在 import 阶段就把 .env 读进来：HF_ENDPOINT / HF_HOME 这类变量必须早于
# huggingface_hub 的 import 才生效（transformers 会在 import 时读取它们）。
load_dotenv_if_present()

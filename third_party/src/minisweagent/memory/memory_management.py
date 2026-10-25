# Copyright 2026 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


'''
Code Adapted from https://github.com/YerbaPage/SWE-Exp/blob/main/moatless/experience/exp_agent/select_agent.py

改动说明（相对原版）
--------------------
原版 ``client = genai.Client()`` 在 import 时就要求 GEMINI_API_KEY（否则直接抛错），
embedding 固定 gemini-embedding-001；且 ``screening()`` 里 query/instruction 两个向量
可能来自不同模型，维度不一致时 matmul 会崩。

现在统一走 :mod:`minisweagent.memory.reasoningbank_llm` 里可配置的 embedder。
'''

import os
import json
import logging
from typing import Dict, List, Tuple

import torch
import torch.nn.functional as F
from torch import Tensor

try:  # 作为包被 import：minisweagent.memory.memory_management
    from .reasoningbank_llm import get_embedder, load_dotenv_if_present
except ImportError:  # 兼容把 memory/ 目录直接加到 sys.path 的旧用法
    from reasoningbank_llm import get_embedder, load_dotenv_if_present  # type: ignore

logger = logging.getLogger(__name__)


def l2_normalize(x: torch.Tensor, dim: int = -1) -> torch.Tensor:
    return F.normalize(x, p=2, dim=dim)


def get_embeddings(texts: list) -> list:
    return get_embedder().embed(list(texts), task_type="document")


def _embed_tensor(texts: List[str], task_type: str = "query") -> Tensor:
    vectors = get_embedder().embed(texts, task_type=task_type)
    return l2_normalize(torch.tensor(vectors, dtype=torch.float32), dim=1)


def embed_query_with_gemini(query: str, dimensionality: int = 3072) -> Tuple[torch.Tensor, str, int]:
    """保留原函数名以兼容旧代码，实际走当前配置的 embedder。"""
    vec = _embed_tensor([query], task_type="query")
    return vec, get_embedder().name, vec.shape[1]


def embed_query_with_qwen(query: str) -> Tuple[torch.Tensor, str, int]:
    vec = _embed_tensor([query], task_type="query")
    return vec, get_embedder().name, vec.shape[1]


def load_cached_embeddings(path: str, dim: int = None) -> Tuple[List[str], List[str], torch.Tensor]:
    ids, texts, vecs = [], [], []
    if not os.path.exists(path):
        logger.info("embedding cache not found, creating empty file: %s", path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w").close()
        return ids, texts, torch.empty(0)

    skipped = 0
    # 同一 id 多次写入时只保留最后一条（重跑同一批实例会重复）
    latest, order = {}, []
    with open(path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            embedding = obj["embedding"]
            if dim and len(embedding) != dim:
                skipped += 1
                continue
            key = str(obj["id"])
            if key not in latest:
                order.append(key)
            latest[key] = (obj.get("text", ""), embedding)

    ids = order
    texts = [latest[k][0] for k in order]
    vecs = [latest[k][1] for k in order]
    if skipped:
        logger.warning(
            "%s 里有 %d 条 embedding 维度和当前模型不一致，已跳过（换过 embedding 模型时会这样）",
            path, skipped,
        )

    if len(vecs) == 0:
        return ids, texts, torch.empty(0)

    emb = torch.tensor(vecs, dtype=torch.float32)
    return ids, texts, l2_normalize(emb, dim=1)


def get_detailed_instruct(task_description: str, query: str) -> str:
    return f'Instruct: {task_description}\nQuery: {query}'


def average_pool(last_hidden_states: Tensor, attention_mask: Tensor) -> Tensor:
    last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
    return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]


def formalize(queries):
    tmp, ids = [], []
    for id, data in enumerate(queries):
        ids.append(id)
        tmp.append(data)
    return tmp, ids


INSTRUCT_TASK = (
    "Given the prior software engineering queries, your task is to analyze a current query's "
    "intent and select relevant prior queries that could help resolve it."
)


def screening(cur_query: str,
              cache_path: str,
              task_id: str = None,
              prefer_model: str = "",) -> Tuple[List[Tuple[str, float]], List[str]]:
    embedder = get_embedder()
    cache_ids, cache_texts, cache_emb = load_cached_embeddings(cache_path, dim=embedder.dim)

    query_vec = _embed_tensor([cur_query], task_type="query")
    record = {
        "id": task_id,
        "text": cur_query,
        "model": embedder.name,
        "embedding": query_vec.squeeze(0).tolist(),
    }
    with open(cache_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    logger.info("appended query embedding to cache: %s", task_id)

    if len(cache_emb) == 0:
        logger.warning("no cached embeddings found in %s", cache_path)
        return [], []

    # Gemini 这类非对称 embedding 要加 "Instruct:" 前缀；bge/OpenAI 对称模型直接算
    query_text = get_detailed_instruct(INSTRUCT_TASK, cur_query) if embedder.uses_instruction else cur_query
    instruct_vec = _embed_tensor([query_text], task_type="query")
    if instruct_vec.shape[1] != cache_emb.shape[1]:
        logger.error(
            "embedding 维度不一致：query=%s cache=%s，请删除 %s 重新积累记忆",
            instruct_vec.shape[1], cache_emb.shape[1], cache_path,
        )
        return [], []

    scores = (instruct_vec @ cache_emb.T).squeeze(0) * 100.0
    id2score = list(zip(cache_ids, scores.tolist()))

    # 排除当前实例自己的历史记录：自己和自己相似度 100%，会让检索永远选中
    # 一个还没写进记忆库的 id（重跑同一批实例时 100% 复现）
    if task_id is not None:
        filtered = [(i, s) for i, s in id2score if str(i) != str(task_id)]
        if filtered:
            id2score = filtered

    id2score.sort(key=lambda x: x[1], reverse=True)
    return id2score, [str(i) for i, _ in id2score]


def select_memory(n: int,
                  reasoning_bank: List[Dict],
                  cur_query: str,
                  task_id: str = None,
                  cache_path: str = "./memory/embeddings.jsonl",
                  prefer_model: str = "gemini") -> List[Dict]:
    if n > 10:
        logger.error("the number of return experiences shouldn't be greater than 10")

    load_dotenv_if_present()
    id2score, ordered_ids = screening(cur_query=cur_query,
                                      task_id=task_id,
                                      cache_path=cache_path,
                                      prefer_model=prefer_model)

    if not ordered_ids:
        return []

    out = []
    for sid in ordered_ids[:n]:
        for item in reasoning_bank:
            if str(item["task_id"]) == sid:
                out.append(item)
                break
    return out

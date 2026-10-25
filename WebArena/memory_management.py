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
原版有两处硬绑定 Google：
  * 模块 import 时就执行 ``vertexai.init(project=..., location="us-central1")``
    —— 没有 GCP 凭据时，连 ``run.py`` 都 import 不进去；
  * 打分用的 ``embed_query_with_gemini`` 固定 ``gemini-embedding-001``（Vertex AI）。
另外原版 ``screening()`` 里 query 向量和 instruction 向量可能来自两个不同模型
（``prefer_model`` 含 "Qwen" 时 query 用 Qwen3-Embedding-8B，instruction 仍然用 Gemini），
维度不一致会直接 matmul 报错。

现在统一走 :mod:`utils.reasoningbank_llm` 里可配置的 embedder，见该模块 docstring。
'''

import os
import json
import logging
from typing import Dict, List, Tuple

import torch
import torch.nn.functional as F
from torch import Tensor

from utils.reasoningbank_llm import get_embedder, load_dotenv_if_present

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# embedding 小工具
# --------------------------------------------------------------------------- #


def l2_normalize(x: torch.Tensor, dim: int = -1) -> torch.Tensor:
    return F.normalize(x, p=2, dim=dim)


def get_embeddings(texts: list) -> list:
    """给一批文本算 embedding（provider 由 RB_EMBED_* 决定）。"""
    return get_embedder().embed(list(texts), task_type="document")


def _embed_tensor(texts: List[str], task_type: str = "query") -> Tensor:
    vectors = get_embedder().embed(texts, task_type=task_type)
    return l2_normalize(torch.tensor(vectors, dtype=torch.float32), dim=1)


def embed_query_with_gemini(query: str, dimensionality: int = 3072) -> Tuple[torch.Tensor, str, int]:
    """保留原函数名以兼容旧代码，实际走当前配置的 embedder。"""
    vec = _embed_tensor([query], task_type="query")
    return vec, get_embedder().name, vec.shape[1]


def embed_query_with_qwen(query: str) -> Tuple[torch.Tensor, str, int]:
    """同上。原版要求本地下载 Qwen3-Embedding-8B（16GB 显存/内存），一般机器跑不动。"""
    vec = _embed_tensor([query], task_type="query")
    return vec, get_embedder().name, vec.shape[1]


# --------------------------------------------------------------------------- #
# 缓存读写
# --------------------------------------------------------------------------- #


def load_cached_embeddings(path: str, dim: int = None) -> Tuple[List[str], List[str], torch.Tensor]:
    """
    读取缓存 embedding。每行: {"id", "text", "embedding"}。

    传入 ``dim`` 时会跳过维度不一致的历史记录 —— 换了 embedding 模型必须跳过，
    否则后面的 matmul 维度对不上（原版在这里会直接抛 RuntimeError）。
    """
    ids, texts, vecs = [], [], []
    if not os.path.exists(path):
        logger.info("embedding cache not found, creating empty file: %s", path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w").close()
        return ids, texts, torch.empty(0)

    skipped = 0
    # 同一个 id 可能被写进来多次（重跑同一批任务时），只保留最后一条，
    # 否则候选里全是重复项，检索会被自己的历史记录挤满。
    latest = {}
    order = []
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
    tmp = []
    ids = []
    for id, data in enumerate(queries):
        ids.append(id)
        tmp.append(data)
    return tmp, ids


# --------------------------------------------------------------------------- #
# 检索
# --------------------------------------------------------------------------- #

INSTRUCT_TASK = (
    "Given the prior web navigation queries, your task is to analyze a current query's "
    "intent and select relevant prior queries that could help resolve it."
)


def screening(cur_query: str,
              cache_path: str,
              task_id: str = None,
              prefer_model: str = "",) -> Tuple[List[Tuple[str, float]], List[str]]:
    """
    对当前 query 算相似度，并把它的 embedding 追加进缓存。

    ``prefer_model`` 仅为兼容旧调用签名保留，实际模型由 RB_EMBED_* 决定。
    """
    embedder = get_embedder()
    cache_ids, cache_texts, cache_emb = load_cached_embeddings(cache_path, dim=embedder.dim)

    query_vec = _embed_tensor([cur_query], task_type="query")

    # 写入当前 query 的 embedding，供后续任务复用
    record = {
        "id": task_id,
        "text": cur_query,
        "model": embedder.name,
        "embedding": query_vec.squeeze(0).tolist(),
    }
    with open(cache_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    logger.info("appended query embedding to cache: webarena.%s", task_id)

    if len(cache_emb) == 0:
        logger.warning("no cached embeddings found in %s", cache_path)
        return [], []

    # instruction-aware embedding：Gemini 这类非对称模型要加 "Instruct:" 前缀；
    # bge / OpenAI embedding 是对称的，加前缀反而压平相似度差距
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

    # 关键修复：排除「当前任务自己」的历史记录。
    # 原版先把当前 query 写进缓存、再拿缓存算相似度，自己和自己相似度恒为 100%，
    # 于是 top-1 永远是当前任务 —— 而当前任务的记忆要跑完才写进库，检索必然落空
    #（重跑同一批任务时 100% 复现：缓存里已有自己的旧向量）。
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
                  cache_path: str = "./memories/embeddings.jsonl",
                  prefer_model: str = "gemini") -> List[Dict]:
    """返回与 ``cur_query`` 最相关的 n 条记忆（reasoning_bank 里的原始条目）。"""
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

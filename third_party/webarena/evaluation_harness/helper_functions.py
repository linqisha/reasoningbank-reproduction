"""Implements helper functions to assist evaluation cases where other evaluators are not suitable."""
import json
from typing import Any
from urllib.parse import urlparse

import requests
from playwright.sync_api import CDPSession, Page

from ..browser_env.env_config import (
    ACCOUNTS,
    GITLAB,
    MAP,
    REDDIT,
    SHOPPING,
    SHOPPING_ADMIN,
    WIKIPEDIA,
)
from ..llms.providers.openai_utils import (
    generate_from_openai_chat_completion,
)

try:
    import gemini_retry  # noqa: F401  # patches google.genai with retry/backoff
except ImportError:
    pass

from google import genai
from google.genai.types import HttpOptions, GenerateContentConfig

# 改动：原版在 import 时就创建 Gemini client，没有 GEMINI_API_KEY 会让整个评测器
# import 失败（run.py 一 reset 环境就崩）。现在改成惰性创建，并优先走 OpenAI 兼容
# 接口（RB_CHAT_*），这样 llm_fuzzy_match 判分也能用 DeepSeek。
client = None
_JUDGE_MODEL = "gemini-2.5-pro"


def _llm_judge(prompt: str, max_tokens: int = 768, temperature: float = 0.0) -> str:
    """让 LLM 做一个判断，返回原始文本。优先 OpenAI 兼容接口，其次 Gemini。"""
    import os

    base = os.environ.get("RB_CHAT_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    key = os.environ.get("RB_CHAT_API_KEY") or os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if base or key:
        from openai import OpenAI

        model = (
            os.environ.get("RB_JUDGE_MODEL")
            or os.environ.get("RB_CHAT_MODEL")
            or "deepseek-chat"
        )
        kwargs = {"api_key": key or "EMPTY"}
        if base:
            kwargs["base_url"] = base
        completion = OpenAI(**kwargs).chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return completion.choices[0].message.content or ""

    if not gemini_key:
        raise RuntimeError(
            "判分需要一个 LLM：配 RB_CHAT_BASE_URL/RB_CHAT_API_KEY（OpenAI 兼容）或 GEMINI_API_KEY"
        )

    global client
    if client is None:
        client = genai.Client(http_options=HttpOptions(api_version="v1"))
    return client.models.generate_content(
        model=_JUDGE_MODEL,
        contents=prompt,
        config=GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens),
    ).text


def shopping_get_auth_token() -> str:
    response = requests.post(
        url=f"{SHOPPING}/rest/default/V1/integration/admin/token",
        headers={"content-type": "application/json"},
        data=json.dumps(
            {
                "username": ACCOUNTS["shopping_site_admin"]["username"],
                "password": ACCOUNTS["shopping_site_admin"]["password"],
            }
        ),
    )
    token: str = response.json()
    return token


def shopping_get_latest_order_url() -> str:
    """Get the latest order url from the shopping website."""

    header = {
        "Authorization": f"Bearer {shopping_get_auth_token()}",
        "Content-Type": "application/json",
    }

    params = {
        "searchCriteria[sortOrders][0][field]": "created_at",
        "searchCriteria[sortOrders][0][direction]": "DESC",
        "searchCriteria[pageSize]": "1",
    }

    response = requests.get(
        f"{SHOPPING}/rest/V1/orders", params=params, headers=header
    )
    assert response.status_code == 200
    response_obj = response.json()["items"][0]
    order_id = int(response_obj["increment_id"])
    order_url = f"{SHOPPING}/sales/order/view/order_id/{order_id}/"
    return order_url


def shopping_get_sku_latest_review_author(sku: str) -> str:
    """Get the latest review for shopping admin."""
    header = {
        "Authorization": f"Bearer {shopping_get_auth_token()}",
        "Content-Type": "application/json",
    }
    response = requests.get(
        f"{SHOPPING}/rest/V1/products/{sku}/reviews", headers=header
    )
    assert response.status_code == 200
    response_obj = response.json()
    if len(response_obj) == 0:
        return ""
    author: str = response_obj[-1]["nickname"]
    return author


def shopping_get_sku_latest_review_rating(sku: str) -> str:
    """Get the latest review for shopping admin."""
    header = {
        "Authorization": f"Bearer {shopping_get_auth_token()}",
        "Content-Type": "application/json",
    }
    response = requests.get(
        f"{SHOPPING}/rest/V1/products/{sku}/reviews", headers=header
    )
    assert response.status_code == 200
    response_obj = response.json()
    if len(response_obj) == 0:
        return ""
    assert response_obj[0]["ratings"][0]["rating_name"] == "Rating"
    rating: str = str(response_obj[-1]["ratings"][0]["percent"])
    return rating


def reddit_get_post_url(url: str) -> str:
    """Get the post url"""
    # Url is http://domain/f/subreddit/post_id/...
    # get domain, subreddit, post_id
    domain = urlparse(url).netloc
    tok_url = urlparse(url).path.split("/")
    # not a valid post/comment url, return the url as is
    if len(tok_url) < 4:
        return url
    if tok_url[1] != "f":
        return url
    subreddit = urlparse(url).path.split("/")[2]
    post_id = urlparse(url).path.split("/")[3]
    scheme = urlparse(url).scheme
    post_url = f"{scheme}://{domain}/f/{subreddit}/{post_id}/"
    return post_url


def gitlab_get_project_memeber_role(page: Page, account_name: str) -> str:
    # get the account index
    try:
        account_idx = page.evaluate(
            f"""(() => {{
                const elements = document.querySelectorAll("td[data-label='Account'] span.gl-avatar-labeled-sublabel");
                let index = -1;  // Default value if not found

                for(let i = 0; i < elements.length; i++) {{
                    if(elements[i].outerText === '@{account_name}') {{
                        index = i;
                        break;
                    }}
                }}

                return index;
            }})()"""
        )

        # get the role
        role: str = page.evaluate(
            f"""(() => {{
                return document.querySelectorAll("td.col-max-role span")[{account_idx}].outerText;
            }})()"""
        )
    except Exception:
        role = ""

    return role


def llm_fuzzy_match(pred: str, reference: str, question: str) -> float:
    """Check whether the prediction matches the reference with GPT4-turbo"""
    messages: list[dict[str, Any]] = []
    # construct the question to ask
    message = "Help a teacher to grade the answer of a student given a question. The reference answer below is ONE part of the full expected answer. Your job is to check whether the student's answer CONTAINS this specific piece of information, even if the student also provides additional correct information.\n"
    message += "If the student's answer contains the reference information (possibly with different phrasing or wording), judge it as correct. Do NOT penalize the student for including extra information beyond the reference.\n"
    message += f"question: {question}\n"
    message += f"reference answer (one part): {reference}\n"
    message += "Important: The string 'N/A' means the task has no meaningful result (e.g., querying orders for a month with no orders). Both 'N/A' and equivalent answers like '0', '$0.00', 'none', or 'no results' should be treated as correct if the reference is 'N/A'.\n"
    message += f"student answer: {pred}\n"
    message += "Conclude the judgement by correct/incorrect/partially correct."
    messages = [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": message},
    ]

    # response = generate_from_openai_chat_completion(
    #     model="gpt-4-1106-preview",
    #     messages=messages,
    #     temperature=0,
    #     max_tokens=768,
    #     top_p=1.0,
    #     context_length=0,
    # ).lower()

    response = _llm_judge(message, max_tokens=768, temperature=0).lower()

    if "partially correct" in response or "incorrect" in response:
        return 0.0
    if "correct" in response:
        return 1.0
    # 原版这里是 assert，模型不按格式回答会直接打断整个评测；改成记一笔、判为不正确
    print(f"[warn] llm_fuzzy_match 无法解析判分结果: {response[:200]!r}")
    return 0.0


def llm_ua_match(pred: str, reference: str, question: str) -> float:
    """Check whether the prediction matches the reference with GPT-turbo"""
    messages: list[dict[str, Any]] = []
    # construct the question to ask
    message = ""
    message += f"task: {question}\n"
    message += f"actual unachievable reason: {reference}\n"
    message += f"reported unachievable reason: {pred}\n"
    message += (
        "The task described above is inherently unachievable due to the reason specified under 'actual unachievable reason'. "
        "An individual previously attempted this task and was unable to complete it. They provided a reason for their failure, "
        "which is listed under 'reported unachievable reason'. Your role is to review both the actual and reported reasons. "
        "Determine if the reported reason aligns with the actual reason, even if implicitly. "
        "If the stated reason is in line with the actual reason, respond with 'same'. Otherwise, respond with 'different'."
    )
    messages = [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": message},
    ]

    # response = generate_from_openai_chat_completion(
    #     model="gpt-4-1106-preview",
    #     messages=messages,
    #     temperature=0,
    #     max_tokens=768,
    #     top_p=1.0,
    #     context_length=0,
    # ).lower()

    response = _llm_judge(message, max_tokens=768, temperature=0).lower()

    if "different" in response:
        return 0.0
    if "same" in response:
        return 1.0
    print(f"[warn] llm_ua_match 无法解析判分结果: {response[:200]!r}")
    return 0.0


class PseudoPage:
    def __init__(self, original_page: Page, url: str):
        self.url = url
        self.original_page = original_page

    def __getattr__(self, attr: str) -> Any:
        # Delegate attribute access to the original page object
        if attr not in ["url"]:
            return getattr(self.original_page, attr)
        else:
            return getattr(self, attr)

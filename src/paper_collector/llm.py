from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from .models import Paper


def summarize_in_chinese(papers: list[Paper]) -> list[Paper]:
    """Add concise Chinese reading notes when an OpenAI-compatible chat API is configured.

    A missing key deliberately leaves the collection usable: paper abstracts remain visible
    and no external text is transmitted.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        return papers
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    for paper in papers:
        prompt = (
            "用简体中文为这篇论文写一条不超过100字的阅读摘要。"
            "说明它解决的问题、核心方法和最重要的证据；保留必要英文技术词，不要夸大未证实的结论。\n\n"
            f"标题：{paper.title}\n摘要：{paper.abstract}"
        )
        payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 180}).encode()
        request = Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=45) as response:  # noqa: S310 - configurable user-selected provider
                result = json.loads(response.read())
            paper.summary_zh = result["choices"][0]["message"]["content"].strip()
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            # A source outage must not prevent a daily paper snapshot from being saved.
            continue
    return papers

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .models import Paper

ATOM = "{http://www.w3.org/2005/Atom}"
LOGGER = logging.getLogger(__name__)
REQUEST_BUDGET_SECONDS = 300


def build_query(categories: list[str]) -> str:
    return " OR ".join(f"cat:{category}" for category in categories)


def _retry_delay(attempt: int, retry_after: str | None = None) -> float:
    delay = 15 * (2**attempt)
    if retry_after:
        try:
            delay = max(delay, int(retry_after))
        except ValueError:
            try:
                retry_date = parsedate_to_datetime(retry_after)
                if retry_date.tzinfo is None:
                    retry_date = retry_date.replace(tzinfo=timezone.utc)
                delay = max(delay, retry_date.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    return delay


def fetch_recent(categories: list[str], max_results: int, user_agent: str, retries: int = 5) -> list[Paper]:
    """Retry transient failures within five minutes; never return an error feed as papers."""
    if retries < 1:
        raise ValueError("retries must be positive")
    query = quote(build_query(categories), safe=":")
    url = (
        "https://export.arxiv.org/api/query?search_query="
        f"{query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    )
    request = Request(url, headers={"User-Agent": user_agent})
    deadline = time.monotonic() + REQUEST_BUDGET_SECONDS
    for attempt in range(retries):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("arXiv request budget exhausted")
            with urlopen(request, timeout=min(45, remaining)) as response:  # noqa: S310 - fixed official endpoint
                root = ElementTree.fromstring(response.read())
            if root.tag != f"{ATOM}feed":
                raise ValueError("arXiv returned an invalid Atom feed")
            return [_parse_entry(entry) for entry in root.findall(f"{ATOM}entry")]
        except HTTPError as error:
            error.close()
            if error.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            delay = _retry_delay(attempt, retry_after)
            if delay >= deadline - time.monotonic():
                raise
            LOGGER.warning("arXiv HTTP %s; retry %s/%s in %.0fs", error.code, attempt + 2, retries, delay)
        except (URLError, TimeoutError, ConnectionError, IncompleteRead, ElementTree.ParseError):
            delay = _retry_delay(attempt)
            if attempt == retries - 1 or delay >= deadline - time.monotonic():
                raise
            LOGGER.warning("arXiv connection or feed interrupted; retry %s/%s in %.0fs", attempt + 2, retries, delay)
        time.sleep(delay)
    raise RuntimeError("arXiv request failed")  # pragma: no cover - each final attempt returns or raises


def _text(entry: ElementTree.Element, name: str) -> str:
    return " ".join((entry.findtext(f"{ATOM}{name}") or "").split())


def _parse_entry(entry: ElementTree.Element) -> Paper:
    abs_url = _text(entry, "id")
    if not abs_url.startswith(("http://arxiv.org/abs/", "https://arxiv.org/abs/")) or not all(
        _text(entry, field) for field in ("title", "summary", "published", "updated")
    ):
        raise ValueError("arXiv returned an error or incomplete paper entry")
    paper_id = abs_url.rsplit("/", 1)[-1]
    links = entry.findall(f"{ATOM}link")
    pdf_url = next((link.attrib["href"] for link in links if link.attrib.get("title") == "pdf"), "")
    return Paper(
        paper_id=paper_id,
        title=_text(entry, "title"),
        abstract=_text(entry, "summary"),
        authors=[_text(author, "name") for author in entry.findall(f"{ATOM}author")],
        published=_text(entry, "published"),
        updated=_text(entry, "updated"),
        categories=[node.attrib["term"] for node in entry.findall(f"{ATOM}category")],
        pdf_url=pdf_url,
        abs_url=abs_url,
    )


def is_after(paper: Paper, cutoff: datetime) -> bool:
    published = datetime.fromisoformat(paper.published.replace("Z", "+00:00"))
    return published >= cutoff.astimezone(timezone.utc)

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .models import Paper

ATOM = "{http://www.w3.org/2005/Atom}"


def build_query(categories: list[str]) -> str:
    return " OR ".join(f"cat:{category}" for category in categories)


def fetch_recent(categories: list[str], max_results: int, user_agent: str) -> list[Paper]:
    query = quote(build_query(categories), safe=":")
    url = (
        "https://export.arxiv.org/api/query?search_query="
        f"{query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    )
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=45) as response:  # noqa: S310 - fixed official endpoint
        root = ElementTree.fromstring(response.read())
    return [_parse_entry(entry) for entry in root.findall(f"{ATOM}entry")]


def _text(entry: ElementTree.Element, name: str) -> str:
    return " ".join((entry.findtext(f"{ATOM}{name}") or "").split())


def _parse_entry(entry: ElementTree.Element) -> Paper:
    abs_url = _text(entry, "id")
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

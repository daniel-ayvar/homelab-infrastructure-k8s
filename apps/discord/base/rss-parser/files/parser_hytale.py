import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from parser_shared_utils import fetch_html, to_rfc822

BASE_URL = "https://hytale.com"
INDEX_URL = "https://hytale.com/news"
DATE_RE = re.compile(r"\b([A-Za-z]+)\s+(\d{1,2})(st|nd|rd|th)\s+(\d{4})\b")
POSTED_BY_RE = re.compile(r"Posted by\s+(.+?)(?:\s{2,}|\s*$)")
DATETIME_RE = re.compile(
    r"\b([A-Za-z]{3})\s+([A-Za-z]{3})\s+(\d{1,2})\s+(20\d{2})\s+(\d{2}):(\d{2}):(\d{2})\s+GMT([+-]\d{4})"
)
POST_CARD_SELECTOR = ".postWrapper .post"
STATE_KEY = "window.__INITIAL_COMPONENTS_STATE__ ="
logger = logging.getLogger("rss-parser")


def _parse_index_date(text: str) -> Optional[datetime]:
    normalized = re.sub(r"\s+", " ", text.replace(",", "")).strip()
    match = DATE_RE.search(normalized)
    if not match:
        return None
    month_name, day, _suffix, year = match.group(1), match.group(2), match.group(3), match.group(4)
    try:
        return datetime.strptime(f"{month_name} {day} {year}", "%B %d %Y").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _parse_datetime_attr(text: str) -> Optional[datetime]:
    match = DATETIME_RE.search(text)
    if not match:
        return None
    _weekday, month_name, day, year, hour, minute, second, offset = match.groups()
    try:
        naive = datetime.strptime(
            f"{month_name} {day} {year} {hour}:{minute}:{second}",
            "%b %d %Y %H:%M:%S",
        )
    except ValueError:
        return None
    sign = 1 if offset.startswith("+") else -1
    offset_hours = int(offset[1:3])
    offset_minutes = int(offset[3:5])
    tzinfo = timezone(
        timedelta(hours=sign * offset_hours, minutes=sign * offset_minutes)
    )
    return naive.replace(tzinfo=tzinfo)


def _extract_posted_by(text: str) -> Optional[str]:
    match = POSTED_BY_RE.search(text)
    return match.group(1).strip() if match else None


def _clean_excerpt(text: str, title: str, author: Optional[str]) -> Optional[str]:
    excerpt = text.replace(title, "").strip()
    if author:
        excerpt = excerpt.replace(f"Posted by {author}", "").strip()
    excerpt = re.sub(r"\b[A-Za-z]+\s+\d{1,2}(st|nd|rd|th)\s+\d{4}\b", "", excerpt).strip()
    return excerpt if len(excerpt) >= 20 else None


def _extract_state_posts(html: str) -> List[dict]:
    start = html.find(STATE_KEY)
    if start == -1:
        logger.warning("hytale: embedded state not found")
        return []
    end = html.find("window.cdnBaseURL", start)
    if end == -1:
        logger.warning("hytale: embedded state truncated before cdnBaseURL")
        return []
    payload = html[start + len(STATE_KEY):end].strip().rstrip(";")
    try:
        state = json.loads(payload)
    except json.JSONDecodeError:
        logger.exception("hytale: failed to decode embedded state JSON")
        return []
    if not state:
        logger.warning("hytale: embedded state empty")
        return []
    posts = state[0].get("posts", [])
    return posts if isinstance(posts, list) else []


def _parse_published_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_items(feed: dict, parser: dict) -> List[dict]:
    index_url = parser.get("index_url") or INDEX_URL
    html = fetch_html(index_url)
    posts = _extract_state_posts(html)
    if posts:
        items = []
        now = datetime.now(timezone.utc)
        for post in posts:
            slug = post.get("slug")
            if not slug:
                continue
            published_at = _parse_published_at(post.get("publishedAt"))
            url = urljoin(BASE_URL, f"/news/{slug}")
            items.append(
                (
                    published_at or now,
                    {
                        "title": post.get("title") or slug,
                        "link": url,
                        "guid": url,
                        "pubDate": to_rfc822(published_at or now),
                        "author": post.get("author") or None,
                        "description": post.get("bodyExcerpt") or None,
                        "image": {
                            "url": urljoin(
                                "https://cdn.hytale.com/",
                                post.get("coverImage", {}).get("s3Key", ""),
                            )
                        }
                        if post.get("coverImage", {}).get("s3Key")
                        else None,
                    },
                )
            )
        items.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in items[:20]]

    logger.warning("hytale: no posts found in embedded state")
    return []

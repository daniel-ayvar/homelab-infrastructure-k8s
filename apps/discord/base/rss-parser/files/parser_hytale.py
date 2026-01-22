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


def build_items(feed: dict, parser: dict) -> List[dict]:
    index_url = parser.get("index_url") or INDEX_URL
    html = fetch_html(index_url)
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(POST_CARD_SELECTOR)
    if cards:
        items = []
        seen = set()
        now = datetime.now(timezone.utc)
        for card in cards:
            href = card.get("href", "")
            if "/news/" not in href:
                continue
            url = urljoin(BASE_URL, href)
            if url in seen:
                continue
            seen.add(url)
            title_tag = card.select_one(".post__details__heading")
            title = title_tag.get_text(" ", strip=True) if title_tag else url
            body_tag = card.select_one(".post__details__body")
            excerpt = body_tag.get_text(" ", strip=True) if body_tag else None
            img_tag = card.select_one("img")
            image_url = img_tag.get("src") if img_tag else None
            meta_author = card.select_one(".post__details__meta__author")
            author_text = (
                meta_author.get_text(" ", strip=True) if meta_author else ""
            )
            author = _extract_posted_by(author_text) or author_text.replace(
                "Posted by", ""
            ).strip()
            time_tag = card.select_one("time[datetime]")
            time_attr = time_tag.get("datetime", "") if time_tag else ""
            date_dt = _parse_datetime_attr(time_attr)
            if not date_dt and time_tag:
                date_dt = _parse_index_date(time_tag.get_text(" ", strip=True))
            items.append(
                {
                    "title": title,
                    "link": url,
                    "guid": url,
                    "pubDate": to_rfc822(date_dt or now),
                    "author": author or None,
                    "description": excerpt,
                    "image": {"url": image_url} if image_url else None,
                }
            )
        return items
    candidates = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/news/" not in href:
            continue
        url = urljoin(BASE_URL, href)
        if not re.search(r"/news/\d{4}/\d{1,2}/", url):
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 6:
            continue
        parent = link.parent
        container_text = parent.get_text(" ", strip=True) if parent else title
        container_text = re.sub(r"\s+", " ", container_text).strip()
        author = _extract_posted_by(container_text)
        date_dt = _parse_index_date(container_text)
        excerpt = _clean_excerpt(container_text, title, author)
        candidates.append((url, title, author, date_dt, excerpt))
    seen = set()
    items = []
    now = datetime.now(timezone.utc)
    for url, title, author, date_dt, excerpt in candidates:
        if url in seen:
            continue
        seen.add(url)
        pub_dt = date_dt or now
        items.append(
            {
                "title": title,
                "link": url,
                "guid": url,
                "pubDate": to_rfc822(pub_dt),
                "author": author,
                "description": excerpt,
            }
        )
    return items

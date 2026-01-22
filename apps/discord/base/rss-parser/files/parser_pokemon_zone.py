import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from parser_shared_utils import fetch_html, to_absolute, to_rfc822

BASE_URL = "https://www.pokemon-zone.com"
SECTION_HEADER = "Latest Pokemon TCG Pocket News and Guides"
DATE_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}\b")
RANGE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s*-\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)?\s*\d{1,2}\b"
)
CATEGORY_RE = re.compile(r"\b(Events|Decks|Game Updates)\b")
AUTHOR_RE = re.compile(r"\bBy\s+([A-Za-z0-9 _.-]+)\b")
FEATURED_CARD_SELECTOR = ".featured-article-preview"
FEATURED_DATE_SELECTOR = ".banner-date__dates"
FEATURED_INTRO_SELECTOR = ".featured-article-preview__intro"
FEATURED_CATEGORY_SELECTOR = ".article-callout-category"
FEATURED_AUTHOR_SELECTOR = ".featured-article-preview__meta-item"


def _to_rfc822(date_text: str) -> str:
    try:
        parsed = datetime.strptime(date_text, "%b %d, %Y")
        return to_rfc822(parsed.replace(tzinfo=timezone.utc))
    except ValueError:
        return to_rfc822(datetime.now(timezone.utc))


def _pick_author(meta_items: List[str]) -> Optional[str]:
    for item in meta_items:
        match = AUTHOR_RE.search(item)
        if match:
            return match.group(1)
    return None


def _parse_index(html: str, base_url: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    stubs = []
    seen = set()
    featured_cards = soup.select(FEATURED_CARD_SELECTOR)
    for card in featured_cards:
        link = card.select_one("a[href]")
        if not link:
            continue
        url = to_absolute(base_url, link.get("href", ""))
        if not url.startswith(base_url):
            continue
        if not re.search(r"/(events|decks|news)/", url):
            continue
        if url in seen:
            continue
        title_tag = card.select_one(".featured-article-preview__title a")
        title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)
        if len(title) < 6:
            continue
        intro_tag = card.select_one(FEATURED_INTRO_SELECTOR)
        intro_text = intro_tag.get_text(" ", strip=True) if intro_tag else None
        category_tag = card.select_one(FEATURED_CATEGORY_SELECTOR)
        category = category_tag.get_text(" ", strip=True) if category_tag else None
        date_tag = card.select_one("time[datetime]")
        date_text = date_tag.get_text(" ", strip=True) if date_tag else ""
        date_attr = date_tag.get("datetime") if date_tag else ""
        banner_date = card.select_one(FEATURED_DATE_SELECTOR)
        event_range = banner_date.get_text(" ", strip=True) if banner_date else None
        meta_items = [
            item.get_text(" ", strip=True)
            for item in card.select(FEATURED_AUTHOR_SELECTOR)
        ]
        author = _pick_author(meta_items)
        img_tag = card.select_one("img")
        image_url = to_absolute(base_url, img_tag.get("src")) if img_tag else None
        stubs.append(
            {
                "title": title,
                "url": url,
                "category": category,
                "author": author,
                "published_date": date_text or date_attr,
                "event_range": event_range,
                "intro": intro_text,
                "image": image_url,
            }
        )
        seen.add(url)
    if stubs:
        return stubs
    header = None
    for tag in soup.find_all(["h1", "h2", "h3"]):
        if SECTION_HEADER in tag.get_text(strip=True):
            header = tag
            break
    scope = header.parent if header else soup
    for link in scope.find_all("a", href=True):
        url = to_absolute(base_url, link["href"])
        if not url.startswith(base_url):
            continue
        if not re.search(r"/(events|decks|news)/", url):
            continue
        title = link.get_text(strip=True)
        if len(title) < 6:
            continue
        card = link.find_parent(["article", "section", "div"]) or scope
        text = " ".join(card.get_text(" ", strip=True).split())
        category_match = CATEGORY_RE.search(text)
        author_match = AUTHOR_RE.search(text)
        published_match = DATE_RE.search(text)
        range_match = RANGE_RE.search(text)
        stubs.append(
            {
                "title": title,
                "url": url,
                "category": category_match.group(1) if category_match else None,
                "author": author_match.group(1) if author_match else None,
                "published_date": published_match.group(0) if published_match else None,
                "event_range": range_match.group(0) if range_match else None,
                "intro": None,
                "image": None,
            }
        )
    deduped = []
    for stub in stubs:
        if stub["url"] in seen:
            continue
        seen.add(stub["url"])
        deduped.append(stub)
    return deduped


def _parse_detail(html: str, stub: Dict) -> Dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1")
    title_text = title.get_text(strip=True) if title else stub["title"]
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    published_match = DATE_RE.search(page_text)
    pub_date_text = stub.get("published_date") or (
        published_match.group(0) if published_match else ""
    )
    pub_date = _to_rfc822(pub_date_text or datetime.now(timezone.utc).strftime("%b %d, %Y"))
    range_match = RANGE_RE.search(page_text)
    display_range = stub.get("event_range") or (range_match.group(0) if range_match else None)
    main = soup.find("main") or (title.parent if title else soup)
    for tag in main.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()
    content_html = str(main).strip() if main else ""
    first_p = main.find("p") if main else None
    description = stub.get("intro") or (first_p.get_text(strip=True) if first_p else None)
    img = main.find("img") if main else None
    img_src = img.get("src") if img else None
    image_url = to_absolute(stub["url"], img_src) if img_src else None
    if not image_url:
        image_url = stub.get("image")
    categories = [cat for cat in [stub.get("category"), "Pokemon TCG Pocket"] if cat]
    item = {
        "title": title_text,
        "link": stub["url"],
        "guid": stub["url"],
        "pubDate": pub_date,
        "author": stub.get("author") or "Pokemon Zone",
        "categories": categories,
        "description": description,
        "content_html": content_html,
    }
    if image_url:
        item["image"] = {"url": image_url}
    if display_range:
        item["event"] = {"displayRange": display_range}
    return item


def _build_item_from_stub(stub: Dict) -> Dict:
    pub_date_text = stub.get("published_date") or datetime.now(timezone.utc).strftime(
        "%b %d, %Y"
    )
    pub_date = _to_rfc822(pub_date_text)
    description = stub.get("intro")
    if not description and stub.get("event_range"):
        description = f"Event window: {stub['event_range']}"
    item = {
        "title": stub.get("title") or stub.get("url"),
        "link": stub.get("url"),
        "guid": stub.get("url"),
        "pubDate": pub_date,
        "author": stub.get("author") or "Pokemon Zone",
        "categories": [cat for cat in [stub.get("category")] if cat],
        "description": description,
        "content_html": None,
    }
    image_url = stub.get("image")
    if image_url:
        item["image"] = {"url": image_url}
    return item


def build_items(feed: dict, parser: dict):
    base_url = feed.get("site") or BASE_URL
    index_url = parser.get("index_url") or base_url
    html = fetch_html(index_url, timeout=12, user_agent=None)
    stubs = _parse_index(html, base_url)
    items = []
    for stub in stubs:
        try:
            detail_html = fetch_html(stub["url"], timeout=12, user_agent=None)
            items.append(_parse_detail(detail_html, stub))
        except Exception:
            items.append(_build_item_from_stub(stub))
    return items

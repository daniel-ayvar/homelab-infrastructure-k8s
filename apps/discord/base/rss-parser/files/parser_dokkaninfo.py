import json
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from parser_shared_utils import fetch_html, first_image_url, strip_ws, to_absolute, to_rfc822

BASE_URL = "https://dokkaninfo.com"
INDEX_URL = "https://dokkaninfo.com/news"
API_URL = "https://dokkaninfo.com/api/news"
NEWS_LINK_RE = re.compile(r"^/news/(\d+)(?:/)?$")
POSTED_BY_RE = re.compile(r"Posted by\s+([A-Za-z0-9 _.-]+)", re.IGNORECASE)
START_DATE_RE = re.compile(r"Start Date:\s*(.+)", re.IGNORECASE)
CARD_CONTAINER_SELECTOR = "div.equal-height-row"
TIMEZONE_OFFSETS = {
    "UTC": 0,
    "GMT": 0,
    "CST": -6,
    "CDT": -5,
    "EST": -5,
    "EDT": -4,
    "PST": -8,
    "PDT": -7,
}


def _is_same_domain(url: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(BASE_URL).netloc
    except Exception:
        return False


def _tzinfo_from_abbr(abbr: str) -> timezone:
    offset_hours = TIMEZONE_OFFSETS.get(abbr.upper())
    if offset_hours is None:
        return timezone.utc
    return timezone(timedelta(hours=offset_hours))


def _parse_datetime_with_tz(text: str) -> Optional[datetime]:
    match = re.search(
        r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)?\s*([A-Z]{2,4})?\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    month, day, year = map(int, match.group(1, 2, 3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    second = int(match.group(6) or 0)
    am_pm = (match.group(7) or "").upper()
    tz_abbr = (match.group(8) or "UTC").upper()
    if am_pm == "PM" and hour < 12:
        hour += 12
    if am_pm == "AM" and hour == 12:
        hour = 0
    tzinfo = _tzinfo_from_abbr(tz_abbr)
    return datetime(year, month, day, hour, minute, second, tzinfo=tzinfo)


def _parse_any_date(text: str) -> datetime | None:
    text = strip_ws(text)
    match = _parse_datetime_with_tz(text)
    if match:
        return match
    match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        year, month, day = map(int, match.groups())
        return datetime(year, month, day, tzinfo=timezone.utc)
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if match:
        month, day, year = map(int, match.groups())
        return datetime(year, month, day, tzinfo=timezone.utc)
    match = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s*(20\d{2})\b", text)
    if match:
        month_name, day, year = match.groups()
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(
                    f"{month_name} {day} {year}", fmt
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _extract_card_stub(link) -> Optional[Dict]:
    href = link.get("href", "").strip()
    if not NEWS_LINK_RE.match(href):
        return None
    url = to_absolute(BASE_URL, href)
    title_parts = [
        strip_ws(tag.get_text(" ", strip=True))
        for tag in link.select(".font-size-1_3 b")
    ]
    title = strip_ws(" ".join(part for part in title_parts if part))
    if not title:
        title = strip_ws(link.get_text(" ", strip=True))
    description = None
    desc_block = link.select_one(".font-size-1")
    if desc_block:
        desc_text = strip_ws(desc_block.get_text(" ", strip=True))
        if "Start Date:" in desc_text:
            desc_text = strip_ws(START_DATE_RE.sub("", desc_text))
        description = desc_text or None
    start_date_text = None
    for div in link.find_all("div"):
        text = strip_ws(div.get_text(" ", strip=True))
        if "Start Date:" in text:
            start_date_text = text
            break
    if not start_date_text:
        match = START_DATE_RE.search(strip_ws(link.get_text(" ", strip=True)))
        if match:
            start_date_text = match.group(1)
    image_url = first_image_url(link, BASE_URL)
    return {
        "title": title or url,
        "url": url,
        "description": description,
        "start_date": start_date_text,
        "image": image_url,
    }


def _parse_index(html: str, max_urls: int) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    stubs = []
    seen = set()
    containers = soup.select(CARD_CONTAINER_SELECTOR)
    for container in containers:
        for link in container.find_all("a", href=True):
            stub = _extract_card_stub(link)
            if not stub:
                continue
            if stub["url"] in seen:
                continue
            seen.add(stub["url"])
            stubs.append(stub)
            if len(stubs) >= max_urls:
                return stubs
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if not NEWS_LINK_RE.match(href):
            continue
        url = to_absolute(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)
        title = strip_ws(link.get_text(" ", strip=True)) or url
        stubs.append(
            {
                "title": title,
                "url": url,
                "description": None,
                "start_date": None,
            }
        )
        if len(stubs) >= max_urls:
            return stubs
    if not stubs:
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            if "/news/" not in href:
                continue
            url = to_absolute(BASE_URL, href)
            if not _is_same_domain(url):
                continue
            if not re.search(r"/news/\d+\b", url):
                continue
            if url in seen:
                continue
            seen.add(url)
            title = strip_ws(link.get_text(" ", strip=True)) or url
            stubs.append(
                {
                    "title": title,
                    "url": url,
                    "description": None,
                    "start_date": None,
                }
            )
            if len(stubs) >= max_urls:
                break
    return stubs


def _parse_detail(html: str, url: str, stub: Optional[Dict] = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = strip_ws(h1.get_text(" ", strip=True))
    else:
        title_tag = soup.find("title")
        title = strip_ws(title_tag.get_text(" ", strip=True)) if title_tag else url
    text_all = strip_ws(soup.get_text(" ", strip=True))
    author = None
    author_match = POSTED_BY_RE.search(text_all)
    if author_match:
        author = strip_ws(author_match.group(1))
    pub_dt = None
    time_el = soup.find("time")
    if time_el and time_el.has_attr("datetime"):
        pub_dt = _parse_any_date(time_el["datetime"])
    if not pub_dt:
        for meta_name in (
            "article:published_time",
            "og:updated_time",
            "pubdate",
            "date",
        ):
            meta = soup.find("meta", attrs={"property": meta_name}) or soup.find(
                "meta", attrs={"name": meta_name}
            )
            if meta and meta.get("content"):
                pub_dt = _parse_any_date(meta["content"])
                if pub_dt:
                    break
    if not pub_dt:
        pub_dt = _parse_any_date(text_all)
    description = None
    for paragraph in soup.find_all("p"):
        text = strip_ws(paragraph.get_text(" ", strip=True))
        if len(text) >= 40:
            description = text
            break
    article = soup.find("article")
    if article:
        content_html = str(article)
    else:
        main = soup.find("main")
        content_html = str(main) if main else None
    image_url = None
    meta_image = soup.find("meta", attrs={"property": "og:image"}) or soup.find(
        "meta", attrs={"name": "og:image"}
    )
    if meta_image and meta_image.get("content"):
        image_url = meta_image["content"]
    if not image_url:
        container = article or main or soup
        image_url = first_image_url(container, BASE_URL)
    if image_url:
        image_url = to_absolute(BASE_URL, image_url)
    if stub:
        if not title or title == url:
            title = stub.get("title", title)
        if not description:
            description = stub.get("description")
        if not image_url:
            image_url = stub.get("image")
        if stub.get("start_date") and not pub_dt:
            parsed = _parse_any_date(stub["start_date"])
            if parsed:
                pub_dt = parsed
    if not pub_dt:
        pub_dt = datetime.now(timezone.utc)
    return {
        "title": title,
        "link": url,
        "guid": url,
        "pubDate": to_rfc822(pub_dt),
        "author": author,
        "description": description,
        "content_html": content_html,
        "image": {"url": image_url} if image_url else None,
    }


def _build_item_from_stub(stub: Dict) -> Dict:
    pub_dt = _parse_any_date(stub.get("start_date") or "") or datetime.now(
        timezone.utc
    )
    image_url = stub.get("image")
    return {
        "title": stub.get("title") or stub.get("url"),
        "link": stub.get("url"),
        "guid": stub.get("url"),
        "pubDate": to_rfc822(pub_dt),
        "author": None,
        "description": stub.get("description"),
        "content_html": None,
        "image": {"url": image_url} if image_url else None,
    }


def _build_items_from_api(max_items: int) -> List[Dict]:
    html = fetch_html(API_URL)
    payload = json.loads(html)
    items = []
    for entry in payload.get("data", [])[:max_items]:
        entry_id = entry.get("id")
        if not entry_id:
            continue
        title = strip_ws(entry.get("title") or "") or f"News {entry_id}"
        summary = strip_ws(entry.get("summary") or "") or None
        banner = entry.get("banner")
        image_url = to_absolute(BASE_URL, banner) if banner else None
        start_at = entry.get("start_at")
        pub_dt = datetime.fromtimestamp(start_at, tz=timezone.utc) if start_at else datetime.now(timezone.utc)
        link = f"{BASE_URL}/news/{entry_id}"
        item = {
            "title": title,
            "link": link,
            "guid": link,
            "pubDate": to_rfc822(pub_dt),
            "author": None,
            "description": summary,
            "content_html": None,
        }
        if image_url:
            item["image"] = {"url": image_url}
        items.append(item)
    return items


def build_items(feed: dict, parser: dict) -> List[dict]:
    max_items = int(parser.get("max_items", 20))
    try:
        return _build_items_from_api(max_items)
    except Exception:
        pass
    index_url = parser.get("index_url") or INDEX_URL
    html = fetch_html(index_url)
    stubs = _parse_index(html, max_items)
    items = []
    for stub in stubs:
        try:
            detail_html = fetch_html(stub["url"])
            items.append(_parse_detail(detail_html, stub["url"], stub))
        except Exception:
            items.append(_build_item_from_stub(stub))
    return items

import datetime
import mimetypes
import threading
import xml.sax.saxutils as xml_escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List

import parser_registry


def _guess_mime_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(url)
    return guessed or "image/jpeg"


def _normalize_item(item: Dict, now: str) -> Dict:
    normalized = dict(item)
    normalized["title"] = str(normalized.get("title") or "")
    normalized["link"] = str(normalized.get("link") or "")
    normalized["guid"] = str(normalized.get("guid") or normalized["link"] or normalized["title"])
    normalized["pubDate"] = str(normalized.get("pubDate") or now)
    normalized["description"] = str(normalized.get("description") or "")
    normalized["content_html"] = normalized.get("content_html")
    image = normalized.get("image")
    if isinstance(image, dict):
        image_url = image.get("url")
    else:
        image_url = image
    normalized["image_url"] = image_url
    return normalized


def _rss_document(feed: Dict) -> str:
    now = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    items = []
    for parser in feed["parsers"]:
        try:
            items.extend(parser_registry.build_items(feed, parser))
        except Exception:
            continue
    seen = set()
    unique_items = []
    for item in items:
        guid = item.get("guid") or item.get("link") or item.get("title")
        if not guid or guid in seen:
            continue
        seen.add(guid)
        unique_items.append(_normalize_item(item, now))
    item_blocks = []
    has_media = False
    for item in unique_items:
        categories = item.get("categories") or []
        category_xml = "".join(
            f"<category>{xml_escape.escape(cat)}</category>" for cat in categories
        )
        content_html = item.get("content_html")
        content_block = (
            f"<content:encoded><![CDATA[{content_html}]]></content:encoded>"
            if content_html
            else ""
        )
        author_block = (
            f"<author>{xml_escape.escape(item['author'])}</author>"
            if item.get("author")
            else ""
        )
        description = item.get("description") or ""
        image_block = ""
        media_block = ""
        image_url = item.get("image_url")
        if image_url:
            mime_type = _guess_mime_type(image_url)
            image_block = (
                f"<enclosure url=\"{xml_escape.escape(image_url)}\" type=\"{xml_escape.escape(mime_type)}\" />"
            )
            media_block = (
                f"<media:content url=\"{xml_escape.escape(image_url)}\" type=\"{xml_escape.escape(mime_type)}\" />"
            )
            has_media = True
        item_blocks.append(
            """
<item>
  <title>{title}</title>
  <link>{link}</link>
  <guid>{guid}</guid>
  <pubDate>{pub}</pubDate>
  {author}{categories}{image}{media}
  <description>{desc}</description>
  {content}
</item>
""".format(
                title=xml_escape.escape(item.get("title", "")),
                link=xml_escape.escape(item.get("link", "")),
                guid=xml_escape.escape(item.get("guid", "")),
                pub=xml_escape.escape(item.get("pubDate", now)),
                author=author_block,
                categories=category_xml,
                image=image_block,
                media=media_block,
                desc=xml_escape.escape(description),
                content=content_block,
            )
        )
    items_xml = "\n".join(item_blocks)
    media_ns = ' xmlns:media="http://search.yahoo.com/mrss/"' if has_media else ""
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"{media_ns}>
  <channel>
    <title>{title}</title>
    <link>{link}</link>
    <description>{desc}</description>
    <lastBuildDate>{pub}</lastBuildDate>
{items}
  </channel>
</rss>
""".format(
        title=xml_escape.escape(f"{feed['name']} RSS"),
        link=xml_escape.escape(feed["site"]),
        desc=xml_escape.escape(f"Placeholder RSS feed for {feed['site']}"),
        pub=now,
        items=items_xml,
        media_ns=media_ns,
    )


class FeedHandler(BaseHTTPRequestHandler):
    def __init__(self, feed: Dict, *args, **kwargs):
        self._feed = feed
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path not in {"/", "/rss", "/rss.xml"}:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        rss_xml = _rss_document(self._feed)
        body = rss_xml.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def _handler_factory(feed: Dict):
    def handler(*args, **kwargs):
        FeedHandler(feed, *args, **kwargs)

    return handler


def start_feed_server(feed: Dict):
    server = HTTPServer(("0.0.0.0", feed["port"]), _handler_factory(feed))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def start_servers(feeds: List[Dict]):
    servers = []
    for feed in feeds:
        server, thread = start_feed_server(feed)
        servers.append((server, thread))
    return servers

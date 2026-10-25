"""Lấy tin từ các nguồn RSS miễn phí + lịch kinh tế, ghi ra site/data/news.json và calendar.json.

Chỉ dùng thư viện chuẩn của Python, chạy được trên GitHub Actions không cần cài gì.
Chỉ lưu tiêu đề, tóm tắt ngắn và link về bài gốc (không chép nguyên bài).
"""
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from common import ROOT, fetch, previous_json, write_json

CONFIG = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))

MAX_AGE = timedelta(hours=72)
MAX_AGE_OFFICIAL = timedelta(days=21)  # thông cáo Fed/EIA/CFTC ra thưa nên giữ lâu hơn
MAX_ITEMS = 400
SUMMARY_LEN = 220

# Nhãn -> từ khoá, so khớp nguyên từ, không phân biệt hoa thường, trên tiêu đề + tóm tắt
TOPICS = {
    "GC": ["gold", "xau", "bullion", "precious metals?", "silver",
           # "vàng" đứng một mình dễ dính "vững vàng", "đất vàng" nên dùng cụm cụ thể
           "giá vàng", "vàng miếng", "vàng nhẫn", "vàng sjc", "vàng thế giới", "vàng trong nước",
           "mua vàng", "bán vàng", "dự trữ vàng", "quỹ vàng", "thị trường vàng", "giá bạc"],
    "ES": ["s&p", "s&p 500", "spx", "dow", "wall street", "stocks?", "equities", "earnings",
           "chứng khoán mỹ", "phố wall"],
    "NQ": ["nasdaq", "nq", "tech stocks", "megacap", "nvidia", "apple", "microsoft", "semiconductors?", "chips?"],
    "CL": ["oil", "crude", "opec", "brent", "wti", "gasoline", "petroleum", "eia", "giá dầu", "xăng dầu"],
    "FED": ["fed", "federal reserve", "fomc", "powell", "rate cuts?", "rate hikes?", "interest rates?",
            "monetary policy", "lãi suất"],
    "MACRO": ["cpi", "pce", "inflation", "jobs report", "payrolls?", "nfp", "gdp", "pmi", "unemployment",
              "retail sales", "treasury yields?", "tariffs?", "lạm phát", "việc làm", "tăng trưởng"],
}
TOPIC_RE = {t: re.compile(r"(?<!\w)(?:" + "|".join(words) + r")(?!\w)", re.IGNORECASE)
            for t, words in TOPICS.items()}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text):
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return WS_RE.sub(" ", text).strip()


def shorten(text, n=SUMMARY_LEN):
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "…"


def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(el, *names):
    for c in el:
        if local(c.tag) in names and (c.text or "").strip():
            return c.text
    return ""


def parse_feed(feed):
    root = ET.fromstring(fetch(feed["url"], timeout=20))
    items = []
    for el in root.iter():
        kind = local(el.tag)
        if kind not in ("item", "entry"):
            continue
        title = clean(child_text(el, "title"))
        if kind == "entry":  # Atom: link nằm trong thuộc tính href
            link = next((c.get("href") for c in el if local(c.tag) == "link" and c.get("href")), "")
        else:
            link = child_text(el, "link").strip()
        summary = clean(child_text(el, "description", "summary", "content"))
        date = parse_date(child_text(el, "pubDate", "published", "updated", "date"))
        if not title or not link:
            continue
        items.append({
            "title": title,
            "link": link,
            "summary": shorten(summary) if summary != title else "",
            "source": feed["name"],
            "lang": feed.get("lang", "en"),
            "official": bool(feed.get("official")),
            "time": date.isoformat() if date else None,
        })
    return items


def tag_topics(item):
    text = f"{item['title']} {item['summary']}"
    tags = [t for t, rx in TOPIC_RE.items() if rx.search(text)]
    if item["source"].startswith("EIA") and "CL" not in tags:
        tags.append("CL")
    if item["source"].startswith("Fed") and "FED" not in tags:
        tags.append("FED")
    return tags


def norm_title(t):
    return re.sub(r"[^\w]", "", t.lower())[:80]


def get_news():
    feeds = CONFIG["feeds"]
    status = []

    def run(feed):
        try:
            return feed, parse_feed(feed), None
        except Exception as e:  # một nguồn lỗi không làm hỏng cả trang
            return feed, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, feeds))

    now = datetime.now(timezone.utc)
    seen, news = set(), []
    for feed, items, err in results:
        status.append({"source": feed["name"], "ok": err is None, "count": len(items), "error": err})
        max_age = MAX_AGE_OFFICIAL if feed.get("official") else MAX_AGE
        for it in items:
            key = norm_title(it["title"])
            if key in seen:
                continue
            if it["time"] and now - datetime.fromisoformat(it["time"]) > max_age:
                continue
            seen.add(key)
            it["topics"] = tag_topics(it)
            news.append(it)

    news.sort(key=lambda x: x["time"] or "", reverse=True)
    return news[:MAX_ITEMS], status


def get_calendar():
    try:
        raw = json.loads(fetch(CONFIG["calendar_url"]))
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    events = [{
        "title": ev.get("title", ""),
        "country": ev.get("country", ""),
        "time": ev.get("date", ""),
        "impact": ev.get("impact", ""),
        "forecast": ev.get("forecast", ""),
        "previous": ev.get("previous", ""),
    } for ev in raw]
    return events, None


def main():
    updated = datetime.now(timezone.utc).isoformat()
    news, status = get_news()
    events, cal_err = get_calendar()

    write_json("news.json", {"updated": updated, "items": news, "sources": status})
    # Nguồn lịch hay giới hạn tần suất (HTTP 429): lỗi thì giữ bản cũ thay vì ghi danh sách rỗng
    if cal_err:
        old = previous_json("calendar.json")
        cal = old if old else {"updated": updated, "events": [], "error": cal_err}
    else:
        cal = {"updated": updated, "events": events, "error": None}
    write_json("calendar.json", cal)

    ok = sum(s["ok"] for s in status)
    print(f"Tin: {len(news)} bài từ {ok}/{len(status)} nguồn. Lịch: {len(cal['events'])} sự kiện"
          + (" (giữ bản cũ)." if cal_err else "."))
    for s in status:
        if not s["ok"]:
            print(f"  ! {s['source']}: {s['error']}")
    if cal_err:
        print(f"  ! Lịch kinh tế: {cal_err}")
    if not news:
        sys.exit("Không lấy được tin nào.")


if __name__ == "__main__":
    main()

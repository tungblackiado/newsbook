"""MODULE 1 — Thu thập, lọc, chấm điểm, loại trùng tin tức.

Luồng: RSS trực tiếp + Google News RSS (theo từ khóa) -> lọc theo thời gian
-> chấm điểm theo từ khóa -> loại trùng -> chọn ứng viên theo từng mảng (vn / intl)
-> (tùy chọn) trích đoạn đầu bài gốc để AI có dữ liệu tóm tắt.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import quote_plus, urlsplit, urlunsplit

import feedparser
import requests

UA = "Mozilla/5.0 (compatible; PersonalNewsBook/1.0; +personal-use)"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


@dataclass
class Item:
    title: str
    link: str
    source: str
    region: str
    published: datetime
    summary: str = ""
    weight: float = 1.0
    score: float = 0.0
    text: str = ""          # đoạn trích bài gốc (nếu lấy được)
    from_gn: bool = False   # đến từ Google News (thường chỉ có tiêu đề)
    id: str = field(default="")


# ---------- tiện ích văn bản ----------
def fold(s: str) -> str:
    """Bỏ dấu tiếng Việt + hạ chữ thường để so khớp từ khóa."""
    s = s.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def clean_html(s: str, limit: int = 600) -> str:
    s = TAG_RE.sub(" ", s or "")
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
          .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
    return WS_RE.sub(" ", s).strip()[:limit]


def norm_link(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))


def strip_source_suffix(title: str) -> str:
    # Google News: "Tiêu đề - Tên báo"
    return re.sub(r"\s+[-–|]\s+[^-–|]{2,40}$", "", title).strip()


# ---------- thu thập ----------
def gn_url(query: str, lang: str) -> str:
    q = quote_plus(f"{query} when:2d")
    if lang == "vi":
        return f"https://news.google.com/rss/search?q={q}&hl=vi&gl=VN&ceid=VN:vi"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _entry_time(e) -> datetime:
    for k in ("published_parsed", "updated_parsed"):
        t = e.get(k)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def fetch_one(name: str, url: str, region: str, weight: float, from_gn: bool):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries:
        title = clean_html(e.get("title", ""), 300)
        link = e.get("link", "")
        if not title or not link:
            continue
        summary = clean_html(e.get("summary", "") or e.get("description", ""), 700)
        if from_gn:  # mô tả của Google News chỉ lặp lại tiêu đề + tên báo
            summary = ""
        src = name
        if from_gn:
            s = e.get("source")
            src = (s.get("title") if s else None) or name
        items.append(Item(title=title, link=link, source=src, region=region,
                          published=_entry_time(e), summary=summary,
                          weight=weight, from_gn=from_gn))
    return items


def collect(cfg: dict):
    """Trả về (danh sách Item, báo cáo từng nguồn)."""
    jobs = []
    for f in cfg.get("feeds", []):
        jobs.append((f["name"], f["url"], f["region"], f.get("weight", 1.0), False))
    for g in cfg.get("google_news", []):
        jobs.append((g["name"], gn_url(g["query"], g.get("lang", "en")),
                     g["region"], g.get("weight", 1.0), True))
    all_items, report = [], []
    for name, url, region, weight, is_gn in jobs:
        try:
            got = fetch_one(name, url, region, weight, is_gn)
            all_items.extend(got)
            report.append((name, "OK", len(got)))
        except Exception as ex:  # một nguồn hỏng không làm hỏng cả bản tin
            report.append((name, f"LỖI: {type(ex).__name__}: {str(ex)[:80]}", 0))
    return all_items, report


# ---------- chấm điểm / loại trùng ----------
def build_keyword_rules(keywords: dict):
    rules = []
    for kw, w in keywords.items():
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(fold(str(kw))) + r"(?![a-z0-9])")
        rules.append((pat, float(w)))
    return rules


def score_items(items, cfg):
    rules = build_keyword_rules(cfg.get("keywords", {}))
    now = datetime.now(timezone.utc)
    for it in items:
        t, s = fold(it.title), fold(it.summary)
        sc = 0.0
        for pat, w in rules:
            if pat.search(t):
                sc += w * 1.5      # xuất hiện ở tiêu đề: trọng số cao hơn
            elif pat.search(s):
                sc += w
        sc = min(sc, 20.0)         # chặn trần để một bài nhồi từ khóa không lấn át
        age_h = max((now - it.published).total_seconds() / 3600, 0)
        recency = max(0.0, 1.5 - age_h / 24)   # bài mới được cộng tối đa 1.5
        it.score = sc * it.weight + recency if sc > 0 else 0.0
    return items


def dedupe(items):
    items = sorted(items, key=lambda i: i.score, reverse=True)
    kept, seen_links = [], set()
    for it in items:
        nl = norm_link(it.link)
        if nl in seen_links:
            continue
        t = fold(strip_source_suffix(it.title))
        if any(SequenceMatcher(None, t, fold(strip_source_suffix(k.title))).ratio() >= 0.82
               for k in kept if k.region == it.region):
            continue
        seen_links.add(nl)
        kept.append(it)
    return kept


def rank(items, cfg):
    s = cfg["settings"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=s.get("lookback_hours", 36))
    fresh = [i for i in items if i.published >= cutoff]
    score_items(fresh, cfg)
    fresh = [i for i in fresh if i.score >= s.get("min_score", 2.0)]
    fresh = dedupe(fresh)
    out = {"vn": [], "intl": []}
    per_src = {}
    for it in fresh:  # đã sắp theo điểm giảm dần
        bucket = out[it.region]
        key = (it.region, it.source)
        if len(bucket) >= s.get("candidates_per_region", 28):
            continue
        if per_src.get(key, 0) >= s.get("max_per_source", 5) + 2:
            continue
        per_src[key] = per_src.get(key, 0) + 1
        bucket.append(it)
    n = 0
    for region in out:
        for it in out[region]:
            n += 1
            it.id = f"{region}{n}"
    return out


# ---------- trích đoạn bài gốc ----------
def enrich(items, chars: int = 1200):
    """Lấy đoạn đầu bài gốc cho các bài RSS trực tiếp (bỏ qua Google News vì link chuyển hướng)."""
    try:
        import trafilatura
    except ImportError:
        return
    for it in items:
        if it.from_gn or chars <= 0:
            continue
        try:
            r = requests.get(it.link, headers={"User-Agent": UA}, timeout=15)
            if r.ok:
                txt = trafilatura.extract(r.text, include_comments=False, include_tables=False)
                if txt:
                    it.text = WS_RE.sub(" ", txt)[:chars]
        except Exception:
            pass

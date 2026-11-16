"""MODULE 2 — Dàn trang và xuất bản EPUB (tạp chí điện tử cá nhân) cho Kindle Paperwhite."""
from __future__ import annotations

import html
import io
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from ebooklib import epub
from PIL import Image, ImageDraw, ImageFont

CSS = """
body { font-family: serif; line-height: 1.45; margin: 0 4%; }
h1 { font-size: 1.5em; margin: 1em 0 0.4em; border-bottom: 2px solid #000; padding-bottom: 0.2em; }
h2 { font-size: 1.2em; margin: 0.2em 0 0.3em; line-height: 1.25; }
.meta { font-size: 0.8em; color: #444; margin: 0 0 0.6em; }
.tag { border: 1px solid #000; padding: 0 0.4em; font-size: 0.75em; margin-right: 0.4em; }
.facts { margin: 0.4em 0; font-size: 0.95em; }
.basis { font-size: 0.75em; color: #444; }
.sowhat { margin: 0.6em 0; padding: 0.4em 0.7em; border-left: 4px solid #000; font-size: 0.95em; }
.src a { font-size: 0.85em; }
ul { padding-left: 1.2em; }
li { margin-bottom: 0.45em; }
.note { font-size: 0.8em; color: #444; margin-top: 2em; }
.hot { font-weight: bold; }
"""

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _font(size: int):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def make_cover(title: str, date_str: str, n_vn: int, n_intl: int) -> bytes:
    W, H = 1600, 2560
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([60, 60, W - 60, H - 60], outline=0, width=10)
    d.rectangle([60, 60, W - 60, 520], fill=0)
    d.text((W // 2, 290), "BẢN TIN SỐ", font=_font(150), fill=255, anchor="mm")
    # chia tiêu đề thành tối đa 3 dòng
    words, lines, cur = title.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 18:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    y = 900
    for ln in lines[:3]:
        d.text((W // 2, y), ln, font=_font(130), fill=0, anchor="mm")
        y += 170
    d.line([300, y + 40, W - 300, y + 40], fill=0, width=8)
    d.text((W // 2, y + 160), date_str, font=_font(110), fill=0, anchor="mm")
    d.text((W // 2, H - 380), f"Trong nước: {n_vn} tin   |   Quốc tế: {n_intl} tin",
           font=_font(70), fill=0, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _fmt_time(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%d/%m %H:%M")


def build_epub(curated: dict, cfg: dict, out_dir: str, ranked_counts=None) -> str:
    s = cfg["settings"]
    tz = ZoneInfo(s.get("timezone", "Asia/Ho_Chi_Minh"))
    now = datetime.now(tz)
    date_long = now.strftime("%d/%m/%Y")
    date_file = now.strftime("%Y-%m-%d")
    title = s.get("title", "Bản tin Hạ tầng AI & DC")
    book_title = f"{title} — {date_long}"

    book = epub.EpubBook()
    book.set_identifier(f"newsbook-{date_file}-{uuid.uuid4().hex[:8]}")
    book.set_title(book_title)
    book.set_language("vi")
    book.add_author(s.get("author", "Bản tin cá nhân"))
    book.add_metadata("DC", "description", "Bản tin tổng hợp tự động từ nhiều nguồn công khai.")

    n_vn = len(curated.get("vn", {}).get("items", []))
    n_intl = len(curated.get("intl", {}).get("items", []))
    book.set_cover("cover.jpg", make_cover(title, date_long, n_vn, n_intl))

    css = epub.EpubItem(uid="css", file_name="style/main.css", media_type="text/css",
                        content=CSS.encode("utf-8"))
    book.add_item(css)

    def page(file_name, ttl, body_html):
        c = epub.EpubHtml(title=ttl, file_name=file_name, lang="vi")
        c.content = f"<html><head><title>{html.escape(ttl)}</title></head><body>{body_html}</body></html>"
        c.add_item(css)
        book.add_item(c)
        return c

    spine, toc = ["nav"], []

    # --- Trang 1: Điểm tin trong ngày ---
    parts = [f"<h1>Điểm tin ngày {date_long}</h1>"]
    for region, label in (("vn", "Trong nước"), ("intl", "Quốc tế")):
        reg = curated.get(region, {})
        parts.append(f"<h2>{label}</h2><ul>")
        for dg in reg.get("digest", []):
            parts.append(f"<li>{html.escape(dg)}</li>")
        top = [i for i in reg.get("items", []) if i["priority"] >= 4][:4]
        for it in top:
            parts.append(f"<li class='hot'>⚑ {html.escape(it['title'])}</li>")
        parts.append("</ul>")
    parts.append("<p class='note'>Tóm tắt do AI biên tập từ tiêu đề/đoạn trích công khai; luôn kiểm chứng ở bài gốc "
                 "trước khi dùng cho quyết định kinh doanh. Chỉ dùng cá nhân, không phát hành lại.</p>")
    c0 = page("digest.xhtml", "Điểm tin trong ngày", "".join(parts))
    spine.append(c0)
    toc.append(epub.Link("digest.xhtml", "Điểm tin trong ngày", "digest"))

    # --- Các mảng tin ---
    n = 0
    for region, label in (("vn", "Tin trong nước"), ("intl", "Tin quốc tế")):
        items = curated.get(region, {}).get("items", [])
        if not items:
            continue
        links = []
        for it in items:
            n += 1
            fn = f"a{n:03d}.xhtml"
            body = [f"<h1>{html.escape(label)}</h1>" if it is items[0] else "",
                    f"<h2>{html.escape(it['title'])}</h2>",
                    f"<p class='meta'><span class='tag'>{html.escape(it['tag'])}</span>"
                    f"{html.escape(it['source'])} · {_fmt_time(it['published'], tz)}</p>",
                    f"<p>{html.escape(it['summary'])}</p>"]
            if it.get("key_facts"):
                body.append("<p class='facts'><b>Số liệu / dữ kiện chính</b></p><ul class='facts'>" +
                            "".join(f"<li>{html.escape(f)}</li>" for f in it["key_facts"]) + "</ul>")
            if it.get("so_what"):
                body.append(f"<div class='sowhat'><b>Ý nghĩa kinh doanh:</b> {html.escape(it['so_what'])}</div>")
            body.append(f"<p class='basis'>Tóm tắt dựa trên: {html.escape(it.get('basis', ''))}</p>")
            body.append(f"<p class='src'><a href='{html.escape(it['link'], quote=True)}'>Đọc bài gốc ›</a></p>")
            c = page(fn, it["title"], "".join(body))
            spine.append(c)
            links.append(epub.Link(fn, it["title"][:90], f"art{n}"))
        toc.append((epub.Section(label), links))

    # --- Trang cuối ---
    srcs = sorted({i["source"] for r in curated.values() for i in r.get("items", [])})
    end = ("<h1>Nguồn trong số này</h1><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in srcs) +
           "</ul><p class='note'>Bản tin được tạo tự động. Chỉnh nguồn/từ khóa trong tệp sources.yaml.</p>")
    c_end = page("sources.xhtml", "Nguồn trong số này", end)
    spine.append(c_end)
    toc.append(epub.Link("sources.xhtml", "Nguồn trong số này", "srcs"))

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"BanTin_ICT_{date_file}.epub")
    epub.write_epub(path, book, {})
    return path

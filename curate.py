"""MODULE 1b — AI biên tập: chọn tin, viết lại tiêu đề, tóm tắt, nêu ý nghĩa kinh doanh.

Dùng Gemini API (gói miễn phí). Chỉ gọi 2 lần/ngày (1 lần/mảng) để nằm gọn
trong hạn mức miễn phí. Nếu AI lỗi -> tự động dùng chế độ dự phòng (tiêu đề + trích đoạn thô).
"""
from __future__ import annotations

import json
import os
import re
import time

TAGS = ["Chính sách", "Thị trường", "Hạ tầng AI/GPU", "Lưu trữ", "Mạng", "Bảo mật",
        "Điện & làm mát", "Chuỗi cung ứng", "Hãng/Đối thủ", "Vĩ mô", "Khác"]

REGION_NAME = {"vn": "TRONG NƯỚC (Việt Nam)", "intl": "QUỐC TẾ"}


def pick_model(client) -> str:
    """Tự dò mô hình Flash-Lite mới nhất còn trong gói miễn phí; có thể ép bằng biến GEMINI_MODEL."""
    env = os.environ.get("GEMINI_MODEL", "").strip()
    if env:
        return env
    names = []
    for m in client.models.list():
        name = getattr(m, "name", "") or ""
        actions = getattr(m, "supported_actions", None) or []
        if actions and "generateContent" not in actions:
            continue
        low = name.lower()
        if any(x in low for x in ("tts", "image", "live", "audio", "embedding", "robotics", "computer")):
            continue
        names.append(name.replace("models/", ""))
    for key in ("flash-lite", "flash"):
        cand = sorted([n for n in names if key in n.lower() and "preview" not in n.lower()], reverse=True)
        if not cand:
            cand = sorted([n for n in names if key in n.lower()], reverse=True)
        if cand:
            return cand[0]
    raise RuntimeError("Không tìm thấy mô hình Gemini phù hợp; hãy đặt biến GEMINI_MODEL.")


def _prompt(region: str, items, n: int, portfolio: str) -> str:
    cands = [{"id": i.id, "title": i.title, "source": i.source,
              "published": i.published.strftime("%Y-%m-%d %H:%M UTC"),
              "text": (i.text or i.summary or "")[:1200]} for i in items]
    return f"""Bạn là biên tập viên bản tin cho một giám đốc phát triển kinh doanh phần cứng tại nhà phân phối ICT ở Việt Nam.
Danh mục hãng đang phân phối: {portfolio}.
Mối quan tâm: hạ tầng AI (GPU/máy chủ), data center, lưu trữ, mạng, bảo mật, điện & làm mát, chính sách, chuỗi cung ứng, vĩ mô.

NHIỆM VỤ: từ danh sách ứng viên mảng {REGION_NAME[region]} bên dưới, chọn tối đa {n} tin giá trị nhất.
- Mỗi sự kiện chỉ chọn 1 bài; ưu tiên đa dạng chủ đề và tin tác động trực tiếp/gián tiếp tới kinh doanh phân phối hạ tầng AI & DC tại Việt Nam.
- Chỉ dùng dữ kiện có trong "title"/"text". TUYỆT ĐỐI không bịa số liệu, tên, ngày. Giữ nguyên tên riêng và số liệu.
- Nếu ứng viên chỉ có tiêu đề (text rỗng): summary_vi chỉ 1 câu và kết thúc bằng " (chỉ có tiêu đề)".
- Viết tiếng Việt; thuật ngữ viết tắt tiếng Anh ở lần đầu xuất hiện trong bản tin thì kèm diễn giải ngắn trong ngoặc.

Với mỗi tin trả về: id (đúng id ứng viên), title_vi (≤110 ký tự), summary_vi (2–3 câu), so_what (1 câu: ý nghĩa với kinh doanh phân phối hạ tầng AI/DC tại Việt Nam; nếu chỉ liên quan gián tiếp thì nói rõ "gián tiếp"; nếu không chắc thì để chuỗi rỗng ""), tag (một trong {TAGS}), priority (1–5, 5 = cần đọc ngay).
Thêm "digest": 3–4 gạch đầu dòng tóm lược xu hướng chung của mảng này.

Chỉ trả về JSON hợp lệ, đúng dạng: {{"digest": ["..."], "items": [{{"id": "...", "title_vi": "...", "summary_vi": "...", "so_what": "...", "tag": "...", "priority": 3}}]}}

ỨNG VIÊN:
{json.dumps(cands, ensure_ascii=False)}"""


def _parse_json(txt: str) -> dict:
    txt = txt.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt)
    return json.loads(txt)


def fallback(items, n: int) -> dict:
    """Dự phòng khi AI lỗi/hết hạn mức: vẫn ra bản tin, chỉ thiếu phần biên tập AI."""
    out = []
    for it in items[:n]:
        out.append({"title": it.title, "link": it.link, "source": it.source,
                    "published": it.published, "summary": (it.text or it.summary)[:350],
                    "so_what": "", "tag": "Khác", "priority": 3})
    return {"digest": ["(Bản dự phòng: AI biên tập không khả dụng, hiển thị tin xếp hạng theo từ khóa.)"],
            "items": out, "ai": False}


def curate_region(client, model: str, region: str, items, n: int, portfolio: str) -> dict:
    if not items:
        return {"digest": [], "items": [], "ai": True}
    from google.genai import types
    prompt = _prompt(region, items, n, portfolio)
    last_err = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json",
                                                   temperature=0.2))
            data = _parse_json(resp.text)
            by_id = {i.id: i for i in items}
            out = []
            for r in data.get("items", []):
                it = by_id.get(r.get("id"))
                if not it:
                    continue
                out.append({"title": r.get("title_vi") or it.title, "link": it.link,
                            "source": it.source, "published": it.published,
                            "summary": r.get("summary_vi", ""), "so_what": r.get("so_what", ""),
                            "tag": r.get("tag") if r.get("tag") in TAGS else "Khác",
                            "priority": int(r.get("priority", 3) or 3)})
            if not out:
                raise ValueError("AI không trả về tin hợp lệ")
            out.sort(key=lambda x: -x["priority"])
            return {"digest": [str(d) for d in data.get("digest", [])][:5], "items": out[:n], "ai": True}
        except Exception as ex:
            last_err = ex
            time.sleep(4 * (attempt + 1))
    print(f"[curate] {region}: AI lỗi ({type(last_err).__name__}: {str(last_err)[:120]}) -> dùng dự phòng")
    return fallback(items, n)


def curate_all(ranked: dict, cfg: dict) -> dict:
    s = cfg["settings"]
    n = s.get("items_per_region", 12)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("[curate] Không có GEMINI_API_KEY -> dùng dự phòng")
        return {r: fallback(items, n) for r, items in ranked.items()}
    try:
        from google import genai
        client = genai.Client(api_key=key)
        model = pick_model(client)
        print(f"[curate] Dùng mô hình: {model}")
    except Exception as ex:
        print(f"[curate] Không khởi tạo được Gemini ({ex}) -> dùng dự phòng")
        return {r: fallback(items, n) for r, items in ranked.items()}
    out = {}
    for region, items in ranked.items():
        out[region] = curate_region(client, model, region, items, n, s.get("portfolio", ""))
        time.sleep(3)  # giãn nhịp để không vượt giới hạn số yêu cầu/phút
    return out

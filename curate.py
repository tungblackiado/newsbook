"""MODULE 1b — AI biên tập, chia 2 giai đoạn để vừa tiết kiệm hạn mức miễn phí vừa tóm tắt sâu.

GIAI ĐOẠN 1 (chọn tin): AI chỉ đọc TIÊU ĐỀ + đoạn trích ngắn của ~28 ứng viên/mảng -> chọn ~12 tin hay nhất.
   -> sau đó chương trình mới tải TOÀN VĂN đúng 12 bài được chọn (không phải cả 28).
GIAI ĐOẠN 2 (tóm tắt sâu): AI đọc toàn văn từng nhóm vài bài -> viết tóm tắt, số liệu chính, ý nghĩa kinh doanh.

Nếu AI lỗi/hết hạn mức -> tự động dùng chế độ dự phòng, bản tin vẫn ra.
"""
from __future__ import annotations

import json
import os
import re
import time

TAGS = ["Chính sách", "Thị trường", "Hạ tầng AI/GPU", "Lưu trữ", "Mạng", "Bảo mật",
        "Điện & làm mát", "Chuỗi cung ứng", "Hãng/Đối thủ", "Vĩ mô", "Khác"]
REGION_NAME = {"vn": "TRONG NƯỚC (Việt Nam)", "intl": "QUỐC TẾ"}
FULLTEXT_MIN = 800   # ngắn hơn mức này coi như "chưa có toàn văn"


# ---------------- khởi tạo AI ----------------
def make_client():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("[curate] Không có GEMINI_API_KEY -> dùng dự phòng")
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as ex:
        print(f"[curate] Không khởi tạo được Gemini ({ex}) -> dùng dự phòng")
        return None


def pick_model(client, preferred: str = "") -> str:
    """Ưu tiên: tên bạn ghi trong sources.yaml > biến GEMINI_MODEL > tự dò Flash-Lite mới nhất."""
    preferred = (preferred or os.environ.get("GEMINI_MODEL", "")).strip()
    if preferred:
        return preferred
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
    raise RuntimeError("Không tìm thấy mô hình Gemini phù hợp; hãy ghi model_select/model_summarize trong sources.yaml.")


class AI:
    def __init__(self, cfg: dict, enabled: bool = True):
        s = cfg["settings"]
        self.client = make_client() if enabled else None
        self.model_sel = self.model_sum = ""
        self.thinking = str(s.get("thinking_level", "") or "").strip()
        if self.client:
            try:
                self.model_sel = pick_model(self.client, s.get("model_select", ""))
                same = (s.get("model_summarize", "") == s.get("model_select", ""))
                self.model_sum = self.model_sel if same else pick_model(self.client, s.get("model_summarize", ""))
                print(f"[curate] Mô hình chọn tin: {self.model_sel} | tóm tắt: {self.model_sum} "
                      f"| thinking_level: {self.thinking or 'mặc định'}")
            except Exception as ex:
                print(f"[curate] Không chọn được mô hình ({ex}) -> dùng dự phòng")
                self.client = None


# ---------------- gọi AI ----------------
def _parse_json(txt: str) -> dict:
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    return json.loads(txt)


def _generate(ai: AI, model: str, prompt: str, thinking: str = ""):
    from google.genai import types
    use_thinking = bool(thinking)
    last = None
    for attempt in range(3):
        try:
            kw = dict(response_mime_type="application/json", temperature=0.2)
            if use_thinking:
                kw["thinking_config"] = types.ThinkingConfig(thinking_level=thinking.upper())
            resp = ai.client.models.generate_content(
                model=model, contents=prompt, config=types.GenerateContentConfig(**kw))
            return _parse_json(resp.text)
        except Exception as ex:
            last = ex
            if use_thinking and "thinking" in str(ex).lower():
                use_thinking = False   # mô hình không hỗ trợ -> thử lại không có thinking_level
                continue
            time.sleep(5 * (attempt + 1))
    raise last


# ---------------- GIAI ĐOẠN 1: chọn tin ----------------
def _select_prompt(region, items, n, portfolio):
    cands = [{"id": i.id, "title": i.title, "source": i.source,
              "published": i.published.strftime("%Y-%m-%d %H:%M UTC"),
              "snippet": (i.text or i.summary or "")[:500]} for i in items]
    return f"""Bạn là biên tập viên bản tin cho một giám đốc phát triển kinh doanh phần cứng tại nhà phân phối ICT ở Việt Nam.
Danh mục hãng đang phân phối: {portfolio}.
Mối quan tâm: hạ tầng AI (GPU/máy chủ), data center, lưu trữ, mạng, bảo mật, điện & làm mát, chính sách, chuỗi cung ứng, vĩ mô.

NHIỆM VỤ: từ danh sách ứng viên mảng {REGION_NAME[region]}, chọn tối đa {n} tin giá trị nhất.
- Mỗi sự kiện chỉ chọn 1 bài; ưu tiên đa dạng chủ đề và tin tác động trực tiếp/gián tiếp tới kinh doanh phân phối hạ tầng AI & DC tại Việt Nam.
- Chỉ dựa vào title/snippet, không suy diễn thêm dữ kiện.
Với mỗi tin: id (đúng id ứng viên), title_vi (≤110 ký tự, dịch/viết lại tiêu đề sang tiếng Việt, giữ nguyên tên riêng), tag (một trong {TAGS}), priority (1–5, 5 = cần đọc ngay).
Thêm "digest": 3–4 gạch đầu dòng tóm lược xu hướng chung của mảng (dựa trên các tiêu đề đã chọn).
Chỉ trả về JSON: {{"digest": ["..."], "items": [{{"id": "...", "title_vi": "...", "tag": "...", "priority": 3}}]}}

ỨNG VIÊN:
{json.dumps(cands, ensure_ascii=False)}"""


def select_fallback(items, n):
    return {"digest": ["(Bản dự phòng: AI chọn tin không khả dụng, hiển thị tin xếp hạng theo từ khóa.)"],
            "picks": [{"item": it, "title": it.title, "tag": "Khác", "priority": 3} for it in items[:n]],
            "ai": False}


def select_region(ai: AI, region, items, cfg):
    s = cfg["settings"]
    n = s.get("items_per_region", 12)
    if not items:
        return {"digest": [], "picks": [], "ai": True}
    if not ai.client:
        return select_fallback(items, n)
    try:
        data = _generate(ai, ai.model_sel, _select_prompt(region, items, n, s.get("portfolio", "")))
        by_id = {i.id: i for i in items}
        picks, seen = [], set()
        for r in data.get("items", []):
            it = by_id.get(r.get("id"))
            if not it or it.id in seen:
                continue
            seen.add(it.id)
            picks.append({"item": it, "title": r.get("title_vi") or it.title,
                          "tag": r.get("tag") if r.get("tag") in TAGS else "Khác",
                          "priority": int(r.get("priority", 3) or 3)})
        if not picks:
            raise ValueError("AI không chọn được tin hợp lệ")
        picks.sort(key=lambda p: -p["priority"])
        return {"digest": [str(d) for d in data.get("digest", [])][:5], "picks": picks[:n], "ai": True}
    except Exception as ex:
        print(f"[curate] {region}: chọn tin lỗi ({type(ex).__name__}: {str(ex)[:120]}) -> dự phòng")
        return select_fallback(items, n)


def select_all(ai: AI, ranked: dict, cfg: dict) -> dict:
    out = {}
    for region, items in ranked.items():
        out[region] = select_region(ai, region, items, cfg)
        time.sleep(3)
    return out


# ---------------- GIAI ĐOẠN 2: tóm tắt sâu từ toàn văn ----------------
def _sum_prompt(region, batch, portfolio):
    arts = []
    for p in batch:
        it = p["item"]
        has_full = len(it.text) >= FULLTEXT_MIN
        arts.append({"id": it.id, "title": it.title, "source": it.source, "priority": p["priority"],
                     "co_toan_van": has_full, "text": (it.text or it.summary or "")})
    return f"""Bạn là biên tập viên bản tin cho một giám đốc phát triển kinh doanh phần cứng tại nhà phân phối ICT ở Việt Nam (danh mục hãng: {portfolio}).
Mảng tin: {REGION_NAME[region]}. Dưới đây là các bài kèm nội dung ("text"). Với MỖI bài hãy viết:
- summary_vi: tóm tắt tiếng Việt. Độ dài: bài priority 4–5 và co_toan_van=true -> 6–8 câu (mạch lạc: chuyện gì xảy ra – số liệu – bối cảnh – tác động); priority 1–3 và co_toan_van=true -> 3–5 câu; co_toan_van=false -> chỉ 1–2 câu và kết thúc bằng " (chỉ có tiêu đề/đoạn trích)".
- key_facts: 3–5 gạch đầu dòng NGẮN nêu số liệu/dữ kiện cụ thể xuất hiện trong text (con số, tên công ty, mốc thời gian, giá trị hợp đồng, công suất…). Nếu không có dữ kiện cụ thể thì trả [].
- so_what: 1–2 câu về ý nghĩa với kinh doanh phân phối hạ tầng AI/DC tại Việt Nam (nếu chỉ liên quan gián tiếp thì nói rõ "gián tiếp"; nếu không chắc thì để "").
QUY TẮC: chỉ dùng dữ kiện có trong "text"/"title"; TUYỆT ĐỐI không bịa số liệu, tên, ngày; giữ nguyên tên riêng và đơn vị; thuật ngữ viết tắt tiếng Anh ở lần đầu xuất hiện thì kèm diễn giải ngắn trong ngoặc.
Chỉ trả về JSON: {{"items": [{{"id": "...", "summary_vi": "...", "key_facts": ["..."], "so_what": "..."}}]}}

BÀI VIẾT:
{json.dumps(arts, ensure_ascii=False)}"""


def summarize_region(ai: AI, region, sel, cfg) -> dict:
    s = cfg["settings"]
    bs = int(s.get("batch_size", 6))
    picks = sel["picks"]
    results = {}
    if ai.client:
        for i in range(0, len(picks), bs):
            batch = picks[i:i + bs]
            try:
                data = _generate(ai, ai.model_sum, _sum_prompt(region, batch, s.get("portfolio", "")),
                                 ai.thinking)
                for r in data.get("items", []):
                    results[r.get("id")] = r
            except Exception as ex:
                print(f"[curate] {region}: tóm tắt lô {i // bs + 1} lỗi ({type(ex).__name__}: {str(ex)[:100]}) -> dự phòng")
            time.sleep(6)   # giãn nhịp để không vượt giới hạn số token/phút
    out = []
    for p in picks:
        it, r = p["item"], results.get(p["item"].id, {})
        full = len(it.text) >= FULLTEXT_MIN
        out.append({
            "title": p["title"], "link": it.link, "source": it.source, "published": it.published,
            "summary": r.get("summary_vi") or (it.text or it.summary or it.title)[:400],
            "key_facts": [str(x) for x in (r.get("key_facts") or [])][:5],
            "so_what": r.get("so_what", "") or "",
            "tag": p["tag"], "priority": p["priority"],
            "basis": "toàn văn" if full else "tiêu đề/đoạn trích",
            "ai": bool(r)})
    return {"digest": sel["digest"], "items": out, "ai": sel["ai"]}


def summarize_all(ai: AI, sel: dict, cfg: dict) -> dict:
    return {region: summarize_region(ai, region, s, cfg) for region, s in sel.items()}

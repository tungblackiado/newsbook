#!/usr/bin/env python3
"""Điều phối 3 module: thu thập -> biên tập AI -> EPUB -> Google Drive.

Cách dùng:
  python main.py --check-feeds        # kiểm tra từng nguồn còn sống không (không gọi AI/Drive)
  python main.py --no-upload          # chạy toàn bộ trừ bước đẩy lên Drive (kiểm thử)
  python main.py --demo               # dữ liệu mẫu offline, không cần mạng/API (kiểm thử định dạng EPUB)
  python main.py                      # chạy đầy đủ (dùng trong GitHub Actions)
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import yaml

import curate
import epub_build
import news_fetch


def demo_ranked():
    now = datetime.now(timezone.utc)
    mk = lambda i, region, t, src, s, h: news_fetch.Item(
        title=t, link=f"https://example.com/{i}", source=src, region=region,
        published=now - timedelta(hours=h), summary=s, id=f"{region}{i}")
    return {
        "vn": [mk(1, "vn", "FPT khởi công trung tâm dữ liệu AI mới tại TP.HCM", "VnExpress - Số hóa",
                  "Dự án có công suất dự kiến hàng chục MW, sử dụng GPU NVIDIA thế hệ mới.", 3),
               mk(2, "vn", "Thị trường lưu trữ doanh nghiệp tăng trưởng nhờ AI", "CafeF - Doanh nghiệp", "", 8)],
        "intl": [mk(3, "intl", "Hyperscalers raise 2027 capex guidance as AI demand stays strong", "DatacenterDynamics",
                    "Major cloud providers lifted spending plans for AI data centres.", 5),
                 mk(4, "intl", "Arista reports record quarter on AI networking", "The Next Platform", "", 10)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sources.yaml")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--check-feeds", action="store_true")
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))

    if a.check_feeds:
        _, report = news_fetch.collect(cfg)
        bad = 0
        for name, status, n in report:
            print(f"{'✔' if status == 'OK' else '✘'} {name:42s} {status} ({n} bài)")
            bad += status != "OK"
        print(f"\nTổng {len(report)} nguồn, lỗi {bad}. Nguồn lỗi/0 bài: hãy xóa hoặc thay URL trong sources.yaml.")
        return

    if a.demo:
        ranked = demo_ranked()
    else:
        items, report = news_fetch.collect(cfg)
        for name, status, n in report:
            print(f"  {name:42s} {status} ({n})")
        ranked = news_fetch.rank(items, cfg)
        print(f"[rank] Ứng viên: trong nước {len(ranked['vn'])}, quốc tế {len(ranked['intl'])}")

    if not any(ranked.values()):
        print("Không có tin đủ điều kiện (kiểm tra nguồn/từ khóa). Dừng, không xuất bản số rỗng.")
        sys.exit(1)

    ai = curate.AI(cfg, enabled=not a.demo)
    sel = curate.select_all(ai, ranked, cfg)                      # Giai đoạn 1: chọn tin theo tiêu đề
    if not a.demo:                                                # tải toàn văn CHỈ cho tin đã chọn
        chars = cfg["settings"].get("fulltext_chars", 12000)
        for region in sel:
            news_fetch.enrich([p["item"] for p in sel[region]["picks"]], chars)
    curated = curate.summarize_all(ai, sel, cfg)                  # Giai đoạn 2: tóm tắt sâu từ toàn văn
    path = epub_build.build_epub(curated, cfg, a.out_dir)
    print(f"[epub] Đã tạo {path} ({os.path.getsize(path)/1024:.0f} KB)")

    if a.demo or a.no_upload:
        return
    import drive_upload
    drive_upload.upload(path, keep=cfg["settings"].get("keep_issues_on_drive", 14))


if __name__ == "__main__":
    main()

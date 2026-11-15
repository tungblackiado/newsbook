"""MODULE 3 — Đẩy EPUB vào thư mục Google Drive.

Có 2 cách, tự chọn theo biến môi trường:
  A) Cầu nối Apps Script (khuyên dùng cho người không rành kỹ thuật): đặt APPS_SCRIPT_URL + APPS_SCRIPT_TOKEN.
     Không cần Google Cloud, không cần màn hình đồng ý OAuth.
  B) OAuth qua Google Cloud: đặt GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN / DRIVE_FOLDER_ID.
"""
from __future__ import annotations

import base64
import json
import os

import requests

PREFIX = "BanTin_ICT_"


# ---------- Cách A: cầu nối Apps Script ----------
def upload_via_apps_script(path: str, keep: int = 14) -> str:
    url = os.environ["APPS_SCRIPT_URL"].strip()
    token = os.environ["APPS_SCRIPT_TOKEN"].strip()
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    payload = {"token": token, "name": os.path.basename(path), "data": data, "keep": keep}
    # text/plain để tránh bước kiểm tra trước (preflight); requests tự theo chuyển hướng của Google
    r = requests.post(url, data=json.dumps(payload),
                      headers={"Content-Type": "text/plain;charset=utf-8"}, timeout=180)
    r.raise_for_status()
    try:
        res = r.json()
    except ValueError:
        raise RuntimeError("Apps Script không trả về JSON — kiểm tra lại URL (phải kết thúc bằng /exec) "
                           "và mục 'Who has access' = Anyone. Phản hồi: " + r.text[:200])
    if not res.get("ok"):
        raise RuntimeError(f"Apps Script từ chối: {res.get('error')}")
    print(f"[drive] Đã tải lên {os.path.basename(path)} qua Apps Script")
    return res.get("id", "")


# ---------- Cách B: OAuth ----------
def upload_via_oauth(path: str, keep: int = 14) -> str:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    folder = os.environ["DRIVE_FOLDER_ID"]
    name = os.path.basename(path)
    media = MediaFileUpload(path, mimetype="application/epub+zip", resumable=False)

    q = f"'{folder}' in parents and name = '{name}' and trashed = false"
    existing = svc.files().list(q=q, fields="files(id)", supportsAllDrives=True,
                                includeItemsFromAllDrives=True).execute().get("files", [])
    if existing:
        fid = existing[0]["id"]
        svc.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
        print(f"[drive] Đã cập nhật {name}")
    else:
        fid = svc.files().create(body={"name": name, "parents": [folder]}, media_body=media,
                                 fields="id", supportsAllDrives=True).execute()["id"]
        print(f"[drive] Đã tải lên {name}")

    q = f"'{folder}' in parents and name contains '{PREFIX}' and trashed = false"
    files = svc.files().list(q=q, fields="files(id,name)", pageSize=200, supportsAllDrives=True,
                             includeItemsFromAllDrives=True).execute().get("files", [])
    files.sort(key=lambda f: f["name"], reverse=True)
    for f in files[keep:]:
        svc.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()
        print(f"[drive] Chuyển vào thùng rác: {f['name']}")
    return fid


def upload(path: str, keep: int = 14) -> str:
    if os.environ.get("APPS_SCRIPT_URL", "").strip():
        return upload_via_apps_script(path, keep)
    if os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        return upload_via_oauth(path, keep)
    raise RuntimeError("Chưa cấu hình cách đẩy lên Drive: cần APPS_SCRIPT_URL + APPS_SCRIPT_TOKEN "
                       "(hoặc bộ khóa OAuth). Kiểm tra mục Secrets trên GitHub.")

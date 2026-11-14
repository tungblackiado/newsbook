"""MODULE 3 — Đẩy EPUB lên thư mục Google Drive bằng OAuth (đăng nhập bằng chính tài khoản Google của bạn).

Lý do không dùng service account: tài khoản dịch vụ mới tạo có dung lượng Drive = 0,
nên không thể sở hữu tệp trong Drive cá nhân (lỗi "Service Accounts do not have storage quota").
"""
from __future__ import annotations

import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_URI = "https://oauth2.googleapis.com/token"
PREFIX = "BanTin_ICT_"


def _service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri=TOKEN_URI,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload(path: str, keep: int = 14) -> str:
    folder = os.environ["DRIVE_FOLDER_ID"]
    svc = _service()
    name = os.path.basename(path)
    media = MediaFileUpload(path, mimetype="application/epub+zip", resumable=False)

    q = f"'{folder}' in parents and name = '{name}' and trashed = false"
    existing = svc.files().list(q=q, fields="files(id)", supportsAllDrives=True,
                                includeItemsFromAllDrives=True).execute().get("files", [])
    if existing:  # chạy lại trong cùng ngày -> cập nhật, không tạo trùng
        fid = existing[0]["id"]
        svc.files().update(fileId=fid, media_body=media, supportsAllDrives=True).execute()
        print(f"[drive] Đã cập nhật {name}")
    else:
        meta = {"name": name, "parents": [folder]}
        fid = svc.files().create(body=meta, media_body=media, fields="id",
                                 supportsAllDrives=True).execute()["id"]
        print(f"[drive] Đã tải lên {name}")

    # Dọn các số cũ (chuyển vào thùng rác, vẫn khôi phục được trong 30 ngày)
    q = f"'{folder}' in parents and name contains '{PREFIX}' and trashed = false"
    files = svc.files().list(q=q, fields="files(id,name)", pageSize=200, supportsAllDrives=True,
                             includeItemsFromAllDrives=True).execute().get("files", [])
    files.sort(key=lambda f: f["name"], reverse=True)
    for f in files[keep:]:
        svc.files().update(fileId=f["id"], body={"trashed": True}, supportsAllDrives=True).execute()
        print(f"[drive] Chuyển vào thùng rác: {f['name']}")
    return fid

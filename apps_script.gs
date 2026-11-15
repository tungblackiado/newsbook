// ===== "Trạm nhận báo" chạy trong Google Apps Script của chính bạn =====
// Việc duy nhất của nó: nhận file EPUB từ GitHub và bỏ vào đúng thư mục Drive.
// SỬA 2 DÒNG NGAY DƯỚI ĐÂY, giữ nguyên dấu ngoặc kép.

const FOLDER_ID = 1KeiT4e7pczDSEu5QoJnt_t4r2PTaIwmF;
const TOKEN = NTTBHQNDK160927111710HANOIVTNM;

function doGet() {
  return ContentService.createTextOutput("Trạm nhận báo newsbook đang chạy.");
}

function doPost(e) {
  try {
    const req = JSON.parse(e.postData.contents);
    if (req.token !== TOKEN) return out({ ok: false, error: "sai mật khẩu" });
    if (!/^BanTin_ICT_[0-9-]+\.epub$/.test(req.name)) return out({ ok: false, error: "tên tệp không hợp lệ" });

    const folder = DriveApp.getFolderById(FOLDER_ID);

    // Cùng tên (chạy lại trong ngày) -> bỏ bản cũ vào thùng rác, tránh trùng
    const same = folder.getFilesByName(req.name);
    while (same.hasNext()) same.next().setTrashed(true);

    const blob = Utilities.newBlob(Utilities.base64Decode(req.data), "application/epub+zip", req.name);
    const file = folder.createFile(blob);

    // Giữ lại N số gần nhất, số cũ hơn chuyển vào thùng rác
    const keep = req.keep || 14;
    const list = [];
    const it = folder.getFiles();
    while (it.hasNext()) {
      const f = it.next();
      if (f.getName().indexOf("BanTin_ICT_") === 0) list.push(f);
    }
    list.sort(function (a, b) { return a.getName() < b.getName() ? 1 : -1; });
    list.slice(keep).forEach(function (f) { f.setTrashed(true); });

    return out({ ok: true, id: file.getId() });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

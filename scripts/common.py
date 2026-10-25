"""Hàm dùng chung cho các script lấy dữ liệu."""
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
UA = "Mozilla/5.0 (compatible; MachThiTruong/1.0)"


def fetch(url, timeout=30, tries=3):
    """Tải URL, thử lại tối đa 3 lần khi lỗi mạng hoặc máy chủ tạm lỗi."""
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    for i in range(tries):
        try:
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except HTTPError as e:
            if e.code < 500 or i == tries - 1:  # lỗi 4xx (sai link, bị chặn, 429) thì không thử lại
                raise
        except (URLError, TimeoutError, ConnectionError):
            if i == tries - 1:
                raise
        time.sleep(3 * (i + 1))


def write_json(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def previous_json(name):
    """Bản dữ liệu đang có: file cũ trên máy, hoặc bản đang đăng trên web (biến SITE_URL, dùng trên GitHub Actions).
    Dùng khi nguồn tạm lỗi, hoặc để khỏi tải lại dữ liệu chưa đổi."""
    path = OUT / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if site:
        try:
            return json.loads(fetch(f"{site}/data/{name}", timeout=15))
        except Exception:
            pass
    return None

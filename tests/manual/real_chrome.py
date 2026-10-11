r"""진짜 Chrome(헤드리스, 임시 프로필)으로 파일을 받아 앱이 기록·이름 변경하는지 확인하는 수동 시험.

실행: .venv\Scripts\python.exe tests\manual\real_chrome.py
- 사용자의 Chrome/프로필·실행 중인 Download Catalog와 섞이지 않도록 모두 임시 폴더와 별도 이름을 쓴다.
- 우리가 띄운 Chrome 프로세스 트리만 종료한다.
"""
import http.server
import json
import os
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["DOWNLOADCATALOG_INSTANCE_SUFFIX"] = "_CHROME_TEST"
ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
CHROME = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
if not CHROME:
    print("Chrome을 찾을 수 없습니다.")
    sys.exit(2)

tmp = Path(tempfile.mkdtemp(prefix="dc_chrome_"))
dl, data, profile = tmp / "dl", tmp / "data", tmp / "profile"
dl.mkdir()
target = dl / "하위 폴더" / "level2" if os.environ.get("REAL_CHROME_SUBDIR") else dl   # Chrome이 받는 폴더
data.mkdir()
(profile / "Default").mkdir(parents=True)
(profile / "Default" / "Preferences").write_text(json.dumps({
    "download": {"default_directory": str(target), "prompt_for_download": False, "directory_upgrade": True},
    "savefile": {"default_directory": str(target)},
}), encoding="utf-8")
(data / "settings.json").write_text(json.dumps({"popup_mode": "off"}), encoding="utf-8")   # 입력창 없이 기록만

PAYLOADS = {"/chrometest.zip": b"PK-first-version" * 5000, "/chrometest2.zip": b"PK-second-version" * 7000}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAYLOADS.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", 'attachment; filename="chrometest.zip"')   # 두 URL이 같은 파일명
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()


def run_chrome(url, wait_for):
    proc = subprocess.Popen([CHROME, "--headless=new", f"--user-data-dir={profile}", "--disable-gpu",
                             "--no-first-run", "--no-default-browser-check", "--disable-extensions", url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 40
    while time.time() < deadline and not wait_for():
        time.sleep(0.5)
    time.sleep(3)    # 앱이 감지·기록할 시간
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    time.sleep(1)


def rows():
    con = sqlite3.connect(data / "catalog.db")
    try:
        return con.execute("select file_name, version, prev_id, source_url, referrer_url, domain from downloads order by id").fetchall()
    finally:
        con.close()


app = subprocess.Popen([PY, "-m", "download_catalog", "--downloads-dir", str(dl), "--data-dir", str(data),
                        "--history-path", str(profile / "Default" / "History"), "--no-first-run-dialog"],
                       cwd=ROOT / "src", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
time.sleep(4)
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label, flush=True)


try:
    run_chrome(f"http://127.0.0.1:{port}/chrometest.zip", lambda: (target / "chrometest.zip").exists())
    files = sorted(p.name for p in target.iterdir())
    r = rows()
    print("  폴더:", files, "\n  기록:", r)
    check("진짜 Chrome이 받은 첫 파일이 폴더에 생김", "chrometest.zip" in files)
    check("앱이 첫 파일을 기록함", len(r) == 1 and r[0][0] == "chrometest.zip")
    check("기록된 경로가 Chrome이 받은 폴더(하위 폴더 포함)와 같음",
          bool(os.path.exists(target / "chrometest.zip")) and bool(r) and
          sqlite3.connect(data / "catalog.db").execute("select file_path from downloads").fetchone()[0] == str(target / "chrometest.zip"))
    check("출처 URL을 찾음(Zone.Identifier 또는 Chrome 기록)", bool(r and r[0][3]) and f"127.0.0.1:{port}" in (r[0][3] or ""))
    check("도메인 저장", bool(r) and r[0][5] == "127.0.0.1")

    run_chrome(f"http://127.0.0.1:{port}/chrometest2.zip", lambda: any("chrometest (1)" in p.name or "chrometest_" in p.name for p in target.iterdir()))
    files = sorted(p.name for p in target.iterdir())
    r = rows()
    print("  폴더:", files, "\n  기록:", [(x[0], x[1], x[2]) for x in r])
    check("같은 이름 두 번째 다운로드: Chrome이 (1)을 붙임 -> 앱이 시각 이름으로 변경", any(f.startswith("chrometest_") and f.endswith(".zip") for f in files)
          and "chrometest (1).zip" not in files)
    check("원래 파일 chrometest.zip은 그대로", "chrometest.zip" in files)
    check("두 번째 파일이 v2로 첫 파일에 연결 기록", len(r) == 2 and r[1][1] == 2 and r[1][2] == 1)
    check("기록된 파일 이름이 실제 폴더의 이름과 일치", len(r) == 2 and r[1][0] in files)
finally:
    app.terminate()
    try:
        app.communicate(timeout=10)
    except Exception:
        app.kill()
    server.shutdown()
print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)

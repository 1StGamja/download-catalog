r"""진짜 Chrome의 '다른 이름으로 저장' 창에서 파일명 자동 변경을 확인하는 수동 시험(화면에 Chrome 창이 잠깐 보임).

실행: .venv\Scripts\python.exe tests\manual\real_chrome_savedialog.py
- 임시 프로필의 Chrome을 '다운로드 전에 저장 위치 확인' 모드로 띄우고, 저장 폴더(감지 폴더의 하위 폴더)에
  같은 이름의 파일을 미리 만들어 둔다. Chrome이 'chrometest (1).zip'을 제안하면 SaveDialogFixer가 바꾸는지 본다.
- 저장 창은 '취소'로 닫고, 우리가 띄운 Chrome 프로세스 트리만 종료한다.
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from download_catalog import savedialog as sd

CHROME = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
if not CHROME:
    print("Chrome을 찾을 수 없습니다.")
    sys.exit(2)

tmp = Path(tempfile.mkdtemp(prefix="dc_chrome_dlg_"))
watch = tmp / "다운로드"
target = watch / "Claude_Output"                    # Chrome이 저장 창을 여는 폴더(감지 폴더의 하위 폴더)
profile = tmp / "profile"
target.mkdir(parents=True)
(profile / "Default").mkdir(parents=True)
(target / "chrometest.zip").write_bytes(b"already here")
(profile / "Default" / "Preferences").write_text(json.dumps({
    "download": {"default_directory": str(target), "prompt_for_download": True, "directory_upgrade": True},
    "savefile": {"default_directory": str(target)},
}), encoding="utf-8")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"PK-new-content" * 4000
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", 'attachment; filename="chrometest.zip"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]

fixer = sd.SaveDialogFixer(watch, process_names=("chrome.exe",), interval=0.2)
fixer.start()
chrome = subprocess.Popen([CHROME, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                           "--disable-extensions", "--window-size=400,300", f"http://127.0.0.1:{port}/chrometest.zip"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = True
try:
    dialog, edit = None, None
    deadline = time.time() + 40
    while time.time() < deadline and not dialog:
        found = sd.find_save_dialogs(("chrome.exe",))
        if found:
            dialog = found[0]
        time.sleep(0.3)
    print(("OK   " if dialog else "FAIL ") + "Chrome의 '다른 이름으로 저장' 창이 열림", flush=True)
    ok &= bool(dialog)
    if dialog:
        folder = sd.find_dialog_folder(dialog)
        print(f"  창의 주소 표시줄에서 읽은 폴더: {folder}")
        ok &= folder is not None and Path(folder) == target
        print(("OK   " if folder == target else "FAIL ") + "창이 열린 폴더(하위 폴더)를 정확히 읽음", flush=True)
        text = ""
        end = time.time() + 6
        while time.time() < end:
            edit = sd.find_filename_edit(dialog)
            text = sd.get_text(edit) if edit else ""
            if text.startswith("chrometest_"):
                break
            time.sleep(0.3)
        print(f"  파일 이름 칸: {text!r}")
        good = text.startswith("chrometest_") and text.endswith(".zip") and "(1)" not in text
        ok &= good
        print(("OK   " if good else "FAIL ") + "Chrome이 제안한 'chrometest (1).zip'이 시각이 붙은 이름으로 바뀜", flush=True)
        ok &= len(fixer.changed) == 1 and fixer.changed[0][0] == "chrometest (1).zip"
        print(("OK   " if len(fixer.changed) == 1 else "FAIL ") + f"원래 제안 이름 기록: {fixer.changed}", flush=True)
        sd.user32.SendMessageW(sd.user32.GetDlgItem(dialog, 2), 0x00F5, 0, 0)   # '취소' 눌러 닫기
        time.sleep(1)
finally:
    fixer.stop()
    subprocess.run(["taskkill", "/PID", str(chrome.pid), "/T", "/F"], capture_output=True)
    server.shutdown()
print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)

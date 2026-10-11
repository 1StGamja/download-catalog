r"""실제 앱(별도 프로세스)으로 놓친 파일 따라잡기 · 제외 규칙 · 두 번째 실행 시 창 열기를 확인하는 수동 시험.

실행: .venv\Scripts\python.exe tests\manual\e2e_app.py
설치된 exe로 시험: E2E_EXE=<DownloadCatalog.exe 경로> 를 지정(창 모드 exe는 콘솔 출력이 없어 "안내 문구" 항목은 실패로 나옴).
"""
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

os.environ["DOWNLOADCATALOG_INSTANCE_SUFFIX"] = "_E2E"
ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
tmp = Path(tempfile.mkdtemp(prefix="dc_e2e_"))
dl, data = tmp / "dl", tmp / "data"
dl.mkdir()


def start(lock=False, extra=()):
    exe = os.environ.get("E2E_EXE")
    base = [exe] if exe else [PY, "-m", "download_catalog"]
    args = base + ["--downloads-dir", str(dl), "--data-dir", str(data),
                   "--history-path", str(tmp / "nohist"), "--no-first-run-dialog"]
    if not lock:
        args.append("--no-lock")
    return subprocess.Popen(args + list(extra), cwd=ROOT / "src",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")


def rows():
    con = sqlite3.connect(data / "catalog.db")
    try:
        return con.execute("select file_name, purpose, auto_skipped from downloads order by id").fetchall()
    finally:
        con.close()


def stop(p):
    p.terminate()
    try:
        return p.communicate(timeout=10)[0]
    except Exception:
        p.kill()
        return ""


def family(pid):
    """venv의 python.exe는 실제 파이썬을 자식 프로세스로 띄우므로, 자식까지 포함한 pid 집합."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId"],
                         capture_output=True, text=True).stdout.split()
    return {pid, *(int(x) for x in out)}


def windows_of(pids):
    found = []
    user32 = ctypes.windll.user32
    pid = wintypes.DWORD()
    cb_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value:
                found.append(buf.value)
        return True

    user32.EnumWindows(cb_type(cb), 0)
    return found


ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label, flush=True)


# --- 1차 실행: 파일 A 기록 ---
(data).mkdir()
(data / "settings.json").write_text(json.dumps({"min_size_mb": 1, "popup_mode": "off"}), encoding="utf-8")
p = start()
time.sleep(4)
(dl / "A.zip").write_bytes(b"A" * 2_000_000)      # 1MB 이상 -> 일반 기록
(dl / "tiny.txt").write_bytes(b"x" * 100)         # 1MB 미만 -> 제외 규칙(기록만, 목적 입력 대상 아님)
time.sleep(7)
out = stop(p)
r = rows()
check("실행 중 받은 파일 기록(A.zip)", ("A.zip", "", 0) in r)
check("제외 규칙: 작은 파일은 기록만 하고 auto_skipped=1", ("tiny.txt", "", 1) in r)
check("popup_mode=off 이므로 입력창 없이 기록만", "Traceback" not in out)

# --- 프로그램이 꺼진 동안 파일 생성 ---
time.sleep(1.2)
(dl / "B.zip").write_bytes(b"B" * 3_000_000)
(dl / "C.zip.crdownload").write_bytes(b"c")       # 받는 중 파일은 무시
(dl / "A (1).zip").write_bytes(b"A" * 2_000_000)  # 이름 충돌 파일: 따라잡기에서는 이름을 바꾸지 않음

# --- 2차 실행: 따라잡기 ---
p = start()
time.sleep(7)
r = rows()
names = [x[0] for x in r]
check("F1 따라잡기: 꺼진 동안 생긴 B.zip 기록", "B.zip" in names)
check("F1 따라잡기: 충돌 이름도 그대로(A (1).zip) 기록", "A (1).zip" in names)
check("F1 따라잡기: .crdownload 무시", not any("crdownload" in n for n in names))
check("F1 따라잡기: 이미 기록된 A.zip 중복 기록 안 함", names.count("A.zip") == 1)
check("따라잡기 파일은 목적 미입력 상태(auto_skipped=0)", ("B.zip", "", 0) in r)
check("따라잡기 중 폴더의 파일 이름은 그대로", sorted(f.name for f in dl.iterdir()) ==
      sorted(["A.zip", "tiny.txt", "B.zip", "C.zip.crdownload", "A (1).zip"]))
s = json.loads((data / "settings.json").read_text(encoding="utf-8"))
check("설정 파일에 last_run, first_run_done 저장", s.get("first_run_done") is True and s.get("last_run"))
check("기존 설정(min_size_mb, popup_mode)은 유지", s.get("min_size_mb") == 1 and s.get("popup_mode") == "off")
stop(p)

# --- 두 번째 실행(U7): 이미 켜진 프로그램의 카탈로그 창이 열린다 ---
first = start(lock=True)
time.sleep(4)
check("처음 실행 후에는 카탈로그 창이 없음", not any("다운로드 기록" in t for t in windows_of(family(first.pid))))
second = start(lock=True)
second.wait(timeout=15)
out2 = second.stdout.read()
time.sleep(2)
check("두 번째 실행은 곧바로 종료(코드 1)", second.returncode == 1)
if not os.environ.get("E2E_EXE"):   # 창 모드 exe는 콘솔이 없어 문구를 출력하지 못한다
    check("두 번째 실행 안내 문구", "이미 실행 중" in out2)
check("U7: 이미 켜진 프로그램에 카탈로그 창이 열림", any("다운로드 기록" in t for t in windows_of(family(first.pid))))
stop(first)
print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)

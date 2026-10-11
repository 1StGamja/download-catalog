r"""실제 앱(별도 프로세스)으로 하위 폴더 감지 설정(켜짐/꺼짐)과 놓친 파일 따라잡기를 확인하는 수동 시험.

실행: .venv\Scripts\python.exe tests\manual\e2e_subfolders.py
설치된 exe로 시험: E2E_EXE=<DownloadCatalog.exe 경로>
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ["DOWNLOADCATALOG_INSTANCE_SUFFIX"] = "_E2E_SUB"
ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
tmp = Path(tempfile.mkdtemp(prefix="dc_e2e_sub_"))
dl, data = tmp / "dl", tmp / "data"
(dl / "프로젝트" / "문서").mkdir(parents=True)
(dl / ".git").mkdir()
data.mkdir()
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label, flush=True)


def write_settings(**kw):
    """기존 설정(마지막 실행 시각 등)은 지우지 않고 필요한 항목만 바꾼다."""
    path = data / "settings.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    path.write_text(json.dumps({**current, "popup_mode": "off", **kw}), encoding="utf-8")


def start():
    exe = os.environ.get("E2E_EXE")
    base = [exe] if exe else [PY, "-m", "download_catalog"]
    return subprocess.Popen(base + ["--downloads-dir", str(dl), "--data-dir", str(data), "--no-lock",
                                    "--history-path", str(tmp / "nohist"), "--no-first-run-dialog"],
                            cwd=ROOT / "src", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def names():
    con = sqlite3.connect(data / "catalog.db")
    try:
        return sorted(r[0] for r in con.execute("select file_name from downloads"))
    finally:
        con.close()


# --- 1) 하위 폴더 감지 켜짐(기본값) ---
write_settings()
p = start()
time.sleep(4)
(dl / "top.zip").write_bytes(b"1" * 500)
(dl / "프로젝트" / "mid.zip").write_bytes(b"2" * 600)
(dl / "프로젝트" / "문서" / "deep.pdf").write_bytes(b"3" * 700)
(dl / ".git" / "obj.bin").write_bytes(b"4" * 800)
(dl / "프로젝트" / "x.zip.crdownload").write_bytes(b"5")
time.sleep(8)
p.terminate()
p.wait(timeout=10)
got = names()
check("켜짐: 최상위·하위·더 깊은 하위 폴더 파일 모두 기록", got == ["deep.pdf", "mid.zip", "top.zip"])
check("켜짐: 숨김 폴더(.git)와 받는 중 파일은 제외", "obj.bin" not in got and not any("crdownload" in n for n in got))

# --- 2) 꺼짐: 최상위만 ---
write_settings(watch_subfolders=False)
p = start()
time.sleep(4)
(dl / "top2.zip").write_bytes(b"6" * 500)
(dl / "프로젝트" / "off-sub.zip").write_bytes(b"7" * 600)      # 꺼져 있는 동안 하위 폴더에 생김
time.sleep(8)
p.terminate()
p.wait(timeout=10)
got = names()
check("꺼짐: 최상위 파일만 기록", "top2.zip" in got)
check("꺼짐: 하위 폴더 파일은 기록하지 않음", "off-sub.zip" not in got)

# --- 3) 다시 켜고 실행 -> 종료 -> 꺼져 있는 동안 하위 폴더에 파일 생성 -> 다음 실행에서 따라잡기 ---
write_settings(watch_subfolders=True)
p = start()
time.sleep(6)
p.terminate()
p.wait(timeout=10)
time.sleep(1.2)
(dl / "프로젝트" / "문서" / "closed-deep.zip").write_bytes(b"8" * 900)    # 프로그램이 꺼져 있는 동안
(dl / "closed-top.zip").write_bytes(b"9" * 900)
p = start()
time.sleep(9)
p.terminate()
p.wait(timeout=10)
got = names()
check("꺼진 동안 하위 폴더에 생긴 파일을 다음 실행에서 따라잡아 기록", "closed-deep.zip" in got)
check("꺼진 동안 최상위에 생긴 파일도 기록", "closed-top.zip" in got)
check("중복 기록 없음", len(got) == len(set(got)))
check("하위 폴더 감지를 끄고 있던 동안의 파일(off-sub.zip)은 거슬러 가져오지 않음(끄면 무시한다는 뜻)", "off-sub.zip" not in got)
print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)

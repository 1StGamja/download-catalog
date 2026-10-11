r"""대량 데이터·큰 파일에서의 속도와 안정성 점검(수동 시험).

실행: .venv\Scripts\python.exe tests\manual\performance.py
"""
import hashlib
import os
import sqlite3
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from download_catalog import versioning
from download_catalog.catalog_window import CatalogWindow
from download_catalog.db import Database
from download_catalog.recorder import record_file
from download_catalog.settings import Settings
from download_catalog.watcher import WatchController

ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""), flush=True)


tmp = Path(tempfile.mkdtemp(prefix="dc_perf_"))
db = Database(tmp / "c.db")
settings = Settings(tmp / "s.json")

# 1) 기록 5,000건 저장
N = 5000
t0 = time.time()
base = datetime.now() - timedelta(days=400)
with sqlite3.connect(tmp / "c.db") as con:
    con.executemany(
        "INSERT INTO downloads (file_name, base_name, file_path, size, sha256, downloaded_at, source_url, domain, purpose, memo) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(f"file{i}.zip", f"file{i}.zip", f"C:/nope/file{i}.zip", i * 1000, f"h{i}",
          (base + timedelta(minutes=i * 100)).strftime("%Y-%m-%d %H:%M:%S"), f"https://site{i % 50}.com/f{i}",
          f"site{i % 50}.com", "업무" if i % 3 == 0 else "", "") for i in range(N)])
check(f"{N}건 일괄 저장", db.count_all() == N, f"{time.time() - t0:.2f}초")

# 2) 검색·필터 속도
t0 = time.time()
for q in ("site7", "file49", "zzzz"):
    db.search(q)
db.search(days=30, unfilled=True)
db.count_unfilled()
elapsed = time.time() - t0
check("검색·필터·집계 5회가 1초 안에 끝남", elapsed < 1.0, f"{elapsed:.3f}초")

# 3) 카탈로그 창 표시·정렬·필터(5,000행)
root = tk.Tk()
root.withdraw()
c = CatalogWindow(root, db, settings)
t0 = time.time()
c.show()
root.update()
shown = time.time() - t0
check("5,000행 카탈로그 창 열기", len(c.tree.get_children()) == N, f"{shown:.2f}초")
t0 = time.time()
c.sort_by("file_name")
root.update()
c.sort_by("size")
root.update()
sorted_time = (time.time() - t0) / 2
check("정렬 한 번이 3초 안에 끝남", sorted_time < 3.0, f"{sorted_time:.2f}초")
t0 = time.time()
c.query.set("site7")
c.refresh()
root.update()
elapsed = time.time() - t0
rows_found = len(c.tree.get_children())
check("검색어 입력 후 목록 갱신이 2초 안에 끝나고 결과가 정확함(site7 -> 100건)",
      elapsed < 2.0 and rows_found == N // 50, f"{elapsed:.2f}초, {rows_found}행")
c.close()
root.destroy()

# 4) 큰 파일 해시 속도(300MB)
big = tmp / "big.bin"
chunk = os.urandom(1024 * 1024)
with open(big, "wb") as f:
    for _ in range(300):
        f.write(chunk)
t0 = time.time()
digest = versioning.sha256_of(big)
dt = time.time() - t0
h = hashlib.sha256()
with open(big, "rb") as f:
    while block := f.read(1 << 20):
        h.update(block)
check("300MB 파일 해시가 정확함(표준 라이브러리와 동일)", digest == h.hexdigest(), f"{dt:.2f}초, {300 / dt:.0f}MB/s")
t0 = time.time()
result = record_file(db, big, history_path=tmp / "none")
check("300MB 파일 기록", result is not None and db.get(result[0])["size"] == 300 * 1024 * 1024, f"{time.time() - t0:.2f}초")

# 5) 동시에 60개 파일이 쏟아져도 모두 기록되는지(감시 + 기록)
folder = tmp / "burst"
folder.mkdir()
done = []
lock = threading.Lock()


def on_file(p):
    r = record_file(db, p, history_path=tmp / "none")
    with lock:
        done.append(r is not None)


ctl = WatchController(folder, on_file, stable_for=0.5)
ctl.start()
for i in range(60):
    (folder / f"burst{i}.dat").write_bytes(os.urandom(2000 + i))
deadline = time.time() + 40
while time.time() < deadline and len(done) < 60:
    time.sleep(0.5)
ctl.stop()
check("60개 파일이 한꺼번에 생겨도 모두 감지·기록", len(done) == 60 and all(done), f"{len(done)}개 처리")
names = {r["file_name"] for r in db.search("burst")}
check("기록된 이름이 누락·중복 없이 60개", len(names) == 60)

print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)

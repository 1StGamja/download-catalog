r"""실제로 실행 중인 트레이: 아이콘 표시, 일시정지 아이콘·문구 갱신, '항상 표시' 설정(IsPromoted) 확인.

실행: .venv\Scripts\python.exe tests\manual\tray_real.py
"""
import queue
import sys
import tempfile
import time
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from download_catalog import tray_promote
from download_catalog.db import Database
from download_catalog.tray import Tray, make_icon, summary_title

ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL ") + label, flush=True)


tmp = Path(tempfile.mkdtemp())
db = Database(tmp / "c.db")
for i in range(3):
    db.add(file_name=f"f{i}.zip", base_name=f"f{i}.zip", file_path=f"C:/x/f{i}.zip", sha256=str(i),
           downloaded_at=time.strftime("%Y-%m-%d %H:%M:%S"))
paused = {"v": False}
events = queue.Queue()
tray = Tray(db, events, lambda: paused["v"], lambda: paused.update(v=not paused["v"]))
tray.start()
time.sleep(2)
check("트레이 아이콘이 화면에 등록됨(visible)", tray.icon.visible)

for state in (False, True, False):          # 예외를 삼키는 refresh() 대신 같은 동작을 직접 실행
    paused["v"] = state
    tray.icon.icon = make_icon(state)
    tray.icon.title = summary_title(db.count_today(), db.count_unfilled(), state)
    tray.icon.update_menu()
    time.sleep(0.3)
    check(f"{'일시정지' if state else '동작 중'} 상태의 마우스 올림 문구 갱신",
          ("일시정지" in tray.icon.title) == state and "오늘 3건 기록 / 목적 안 쓴 것 3건" in tray.icon.title)

# 숨김 칸에 가려지지 않도록 IsPromoted=1을 설정하는지(이 시험 프로세스의 실행 파일 기준)
exe = tray_promote.current_exe()
count = tray_promote.promote(exe)
promoted = []
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, tray_promote.SETTINGS_KEY) as root_key:
    i = 0
    while True:
        try:
            name = winreg.EnumKey(root_key, i)
        except OSError:
            break
        i += 1
        with winreg.OpenKey(root_key, name) as k:
            try:
                path = winreg.QueryValueEx(k, "ExecutablePath")[0]
                if tray_promote._norm(path) == tray_promote._norm(exe):
                    promoted.append(winreg.QueryValueEx(k, "IsPromoted")[0])
            except OSError:
                pass
check(f"트레이 항목(IsPromoted)이 1로 설정됨 (항목 {count}개): {exe}", count >= 1 and promoted and all(v == 1 for v in promoted))
tray.stop()
print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)

r"""진짜 윈도우 '다른 이름으로 저장' 창에서 파일명 자동 변경(SaveDialogFixer)을 확인하는 수동 시험.

실행: .venv\Scripts\python.exe tests\manual\save_dialog_real.py
(Chrome 저장 창과 같은 윈도우 표준 창을 tkinter로 띄우고, 프로세스 이름만 python.exe로 바꿔 시험한다.)
"""
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from download_catalog import savedialog as sd

folder = Path(tempfile.mkdtemp(prefix="dc_dlg_"))
(folder / "a.zip").write_bytes(b"x")
fixer = sd.SaveDialogFixer(folder, process_names=("python.exe",), interval=0.2)
fixer.start()
root = tk.Tk()
root.withdraw()
results = {}


def click_save_after(delay, key):
    def run():
        time.sleep(delay)
        dialogs = sd.find_save_dialogs(("python.exe",))
        edit = sd.find_filename_edit(dialogs[0]) if dialogs else None
        results[key] = {"found": bool(dialogs), "text": sd.get_text(edit) if edit else None}
        if dialogs:
            sd.user32.SendMessageW(sd.user32.GetDlgItem(dialogs[0], 1), 0x00F5, 0, 0)   # '저장' 버튼 클릭

    threading.Thread(target=run, daemon=True).start()


cases = [("충돌 이름(원래 파일 있음)", "a (1).zip"), ("충돌처럼 보이지만 원래 파일 없음", "b (1).zip"),
         ("충돌 아닌 이름", "c.zip")]
ok = True
for label, initial in cases:
    click_save_after(2.0, initial)
    chosen = filedialog.asksaveasfilename(parent=root, title="다른 이름으로 저장", initialdir=str(folder),
                                          initialfile=initial)
    final = Path(chosen).name
    changed = final != initial
    expected_change = initial == "a (1).zip"
    good = results[initial]["found"] and (changed == expected_change) and (
        final.startswith("a_") and final.endswith(".zip") if expected_change else final == initial)
    ok &= good
    print(("OK   " if good else "FAIL ") + f"{label}: 제안 {initial!r} -> 저장 이름 {final!r}", flush=True)

# 감지 폴더(folder)의 하위 폴더에서 저장 창이 열린 경우 — 사용자 화면과 같은 상황
nested = folder / "다운로드" / "Claude_Output"
nested.mkdir(parents=True)
(nested / "DB접속우회접속차단방안.pptx").write_bytes(b"x")
(folder / "루트에만있음.pptx").write_bytes(b"x")          # 감지 폴더 바로 아래에만 있는 파일


def nested_case(label, initial, initialdir, expect_change, prefix=None):
    global ok
    key = f"nested-{initial}"
    click_save_after(2.5, key)
    chosen = filedialog.asksaveasfilename(parent=root, title="다른 이름으로 저장", initialdir=str(initialdir),
                                          initialfile=initial)
    final = Path(chosen).name
    changed = final != initial
    good = results[key]["found"] and changed == expect_change and (
        final.startswith(prefix) and final.endswith(".pptx") if expect_change else final == initial)
    ok &= good
    print(("OK   " if good else "FAIL ") + f"{label}: 제안 {initial!r} -> 저장 이름 {final!r}", flush=True)


nested_case("하위 폴더에서 열린 창 + 그 폴더에 원본 있음(사용자 화면과 같은 상황)",
            "DB접속우회접속차단방안 (1).pptx", nested, True, "DB접속우회접속차단방안_")
nested_case("하위 폴더에서 열린 창 + 원본이 이 폴더에는 없음(다른 폴더에만 있음)",
            "루트에만있음 (1).pptx", nested, False)
nested_case("감지 폴더 바로 아래에서 열린 창 + 원본 있음", "루트에만있음 (1).pptx", folder, True, "루트에만있음_")
# 창의 주소 표시줄에서 폴더를 읽는지 직접 확인
click_save_after(2.5, "addr")
filedialog.asksaveasfilename(parent=root, title="다른 이름으로 저장", initialdir=str(nested), initialfile="z.pptx")
fixer.get_dir()  # (속성 접근 확인)
addr = results["addr"]
print("OK   저장 창이 열렸고 파일명 칸을 읽음: " + repr(addr["text"]) if addr["found"] else "FAIL 저장 창을 찾지 못함")
ok &= bool(addr["found"])

# 일시정지 중에는 바꾸지 않는다
fixer.is_paused = lambda: True
click_save_after(2.0, "paused")
chosen = filedialog.asksaveasfilename(parent=root, title="다른 이름으로 저장", initialdir=str(folder),
                                      initialfile="a (1).zip")
good = Path(chosen).name == "a (1).zip"
ok &= good
print(("OK   " if good else "FAIL ") + f"일시정지 중에는 이름을 바꾸지 않음: {Path(chosen).name!r}")
fixer.stop()
print("\nALL OK" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)

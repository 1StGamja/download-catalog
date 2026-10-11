"""U3. 목적을 입력하지 않은 기록을 키보드만으로 하나씩 빠르게 채우는 창."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

from .catalog_window import open_in_explorer
from .popup import FONT, FONT_SMALL, FONT_TITLE, suggest_note, type_badge
from .urlutil import human_size


class ReviewWindow:
    def __init__(self, root, db, settings, on_change=None):
        self.root, self.db, self.settings = root, db, settings
        self.on_change = on_change or (lambda: None)
        self.win = None
        self.ids, self.index = [], 0

    def show(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.lift()
            return
        self.ids = [r["id"] for r in self.db.unfilled_rows()]   # 시작 시점의 목록(최신순)
        if not self.ids:
            messagebox.showinfo("목적 입력", "목적을 입력하지 않은 기록이 없습니다.")
            return
        self.index = 0
        self._build()
        self._load()

    # ---- 화면 ----
    def _build(self):
        self.win = win = tk.Toplevel(self.root)
        win.title("목적 입력하지 않은 기록 정리")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.after(300, lambda: win.attributes("-topmost", False))
        f = ttk.Frame(win, padding=18)
        f.grid()
        self.counter = ttk.Label(f, font=FONT_SMALL, foreground="#2563eb")
        self.counter.grid(row=0, column=0, columnspan=2, sticky="w")
        head = ttk.Frame(f)
        head.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.badge = tk.Label(head, font=("Malgun Gothic", 10, "bold"), fg="white", padx=6, pady=2)
        self.badge.pack(side="left", padx=(0, 8))
        self.name = ttk.Label(head, font=FONT_TITLE, wraplength=520)
        self.name.pack(side="left")
        self.info = ttk.Label(f, font=FONT_SMALL, foreground="#555", wraplength=560)
        self.info.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.hint = ttk.Label(f, font=FONT_SMALL, foreground="#2563eb")
        self.hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(f, text="목적", font=FONT).grid(row=4, column=0, sticky="w", padx=(0, 8))
        self.purpose = ttk.Combobox(f, width=45, font=FONT)
        self.purpose.grid(row=4, column=1, sticky="ew", pady=4, ipady=5)
        ttk.Label(f, text="메모", font=FONT).grid(row=5, column=0, sticky="w", padx=(0, 8))
        self.memo = ttk.Entry(f, width=50, font=FONT)
        self.memo.grid(row=5, column=1, sticky="ew", pady=4, ipady=5)

        style = ttk.Style(self.root)
        style.configure("Rev.TButton", font=FONT, padding=(12, 5))
        bar = ttk.Frame(f)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        for text, cmd in (("파일 열기", self.open_file), ("폴더 열기", self.open_folder),
                          ("이전", self.back), ("건너뛰기 (Ctrl+→)", self.skip),
                          ("저장 후 다음 (Enter)", self.save_next)):
            ttk.Button(bar, text=text, style="Rev.TButton", command=cmd).pack(side="left", padx=3)
        ttk.Label(f, text="Tab: 목적↔메모 이동 · Enter: 저장하고 다음 · Esc: 닫기",
                  font=("Malgun Gothic", 10), foreground="#777").grid(row=7, column=0, columnspan=2,
                                                                       sticky="w", pady=(8, 0))
        win.bind("<Return>", lambda _e: self.save_next())
        win.bind("<Escape>", lambda _e: self.close())
        win.bind("<Control-Right>", lambda _e: self.skip())
        win.bind("<Control-Left>", lambda _e: self.back())
        win.protocol("WM_DELETE_WINDOW", self.close)

    def _load(self):
        """index번째 기록을 화면에 채운다. 없는 기록이면 건너뛴다."""
        while self.index < len(self.ids):
            row = self.db.get(self.ids[self.index])
            if row is not None:
                break
            self.index += 1
        else:
            self._finished()
            return
        self.row = row
        text, color = type_badge(row["file_name"])
        self.badge.config(text=text, bg=color)
        self.counter.config(text=f"{self.index + 1} / {len(self.ids)}")
        self.name.config(text=row["file_name"])
        exists = "있음" if os.path.exists(row["file_path"]) else "없음(이동·삭제됨)"
        self.info.config(text=f"{row['downloaded_at']} · {human_size(row['size'])} · "
                              f"{row['domain'] or '출처를 알 수 없음'} · 파일 {exists}")
        purpose, memo, hint = suggest_note(self.db, self.settings, row)
        values = list(self.settings.purposes)
        if purpose not in values:
            values.insert(0, purpose)
        self.purpose.config(values=values)
        self.purpose.set(purpose)
        self.memo.delete(0, "end")
        self.memo.insert(0, memo)
        self.memo.select_range(0, "end")
        self.hint.config(text=hint)
        self.memo.focus_set()

    # ---- 동작 ----
    def save_next(self):
        self.db.update_note(self.row["id"], self.purpose.get().strip(), self.memo.get().strip())
        self.on_change()
        self.index += 1
        self._load()

    def skip(self):
        self.index += 1
        self._load()

    def back(self):
        if self.index > 0:
            self.index -= 1
            self._load()

    def open_file(self):
        if os.path.exists(self.row["file_path"]):
            os.startfile(self.row["file_path"])

    def open_folder(self):
        open_in_explorer(self.row["file_path"])

    def _finished(self):
        self.close()
        remaining = self.db.count_unfilled()
        text = "모두 처리했습니다." if not remaining else f"끝까지 확인했습니다. (아직 입력하지 않은 기록 {remaining}건)"
        messagebox.showinfo("목적 입력", text)

    def close(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None
        self.on_change()

"""환경설정 창(탭: 일반 / 팝업 / 제외 규칙 / 정보)."""
import os
import tkinter as tk
from urllib.parse import quote
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import DEVELOPER_EMAIL, DEVELOPER_NAME, __version__
from .settings import (DEFAULT_PURPOSES, FONT_SIZES, normalize_domain, normalize_ext,
                       default_watch_dir)
from .urlutil import human_size

FONT = ("Malgun Gothic", 11)
FONT_B = ("Malgun Gothic", 11, "bold")
GRAY = "#555"
POPUP_MODE_LABELS = (
    ("popup", "바로 팝업 — 파일을 받으면 입력창이 바로 뜹니다"),
    ("quiet", "조용히 알림 — 작은 알림만 띄우고, 누르면 입력창이 열립니다"),
    ("off", "사용 안 함 — 입력창을 띄우지 않습니다(나중에 '목적 안 쓴 기록'에서 입력)"),
)


class ListEditor(ttk.Frame):
    """항목 목록을 추가·삭제(·순서 변경)하는 작은 부품."""

    def __init__(self, parent, normalize=lambda s: s.strip(), reorder=False, height=7):
        super().__init__(parent)
        self.normalize = normalize
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box, height=height, font=FONT, activestyle="none", exportselection=False)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        side = ttk.Frame(self)
        side.pack(fill="x", pady=(6, 0))
        self.entry = ttk.Entry(side, font=FONT, width=24)
        self.entry.pack(side="left", ipady=2)
        self.entry.bind("<Return>", lambda _e: (self.add(), "break")[1])
        ttk.Button(side, text="추가", command=self.add).pack(side="left", padx=(6, 0))
        ttk.Button(side, text="삭제", command=self.remove).pack(side="left", padx=(4, 0))
        if reorder:
            ttk.Button(side, text="▲", width=3, command=lambda: self.move(-1)).pack(side="left", padx=(8, 0))
            ttk.Button(side, text="▼", width=3, command=lambda: self.move(1)).pack(side="left", padx=(2, 0))

    def items(self):
        return list(self.listbox.get(0, "end"))

    def set_items(self, items):
        self.listbox.delete(0, "end")
        for item in items:
            self.listbox.insert("end", item)

    def add(self):
        value = self.normalize(self.entry.get())
        if value and value not in self.items():
            self.listbox.insert("end", value)
        self.entry.delete(0, "end")

    def remove(self):
        for index in reversed(self.listbox.curselection()):
            self.listbox.delete(index)

    def move(self, delta):
        sel = self.listbox.curselection()
        if not sel:
            return
        i, j = sel[0], sel[0] + delta
        if 0 <= j < self.listbox.size():
            value = self.listbox.get(i)
            self.listbox.delete(i)
            self.listbox.insert(j, value)
            self.listbox.selection_set(j)


class SettingsWindow:
    def __init__(self, root, settings, db, data_dir, current_dir, on_apply, is_autostart=None):
        """current_dir()은 지금 감시 중인 폴더, on_apply(dict)는 값을 적용(실패 시 예외)."""
        self.root, self.settings, self.db, self.data_dir = root, settings, db, Path(data_dir)
        self.current_dir, self.on_apply = current_dir, on_apply
        self.is_autostart = is_autostart or (lambda: False)
        self.win = None

    def show(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            return
        self.win = win = tk.Toplevel(self.root)
        win.title("Download Catalog - 환경설정")
        win.resizable(False, False)
        style = ttk.Style(self.root)
        style.configure("Set.TButton", font=FONT, padding=(10, 4))
        style.configure("Set.TCheckbutton", font=FONT)
        style.configure("Set.TRadiobutton", font=FONT)
        self.root.option_add("*TCombobox*Listbox.font", FONT)

        outer = ttk.Frame(win, padding=12)
        outer.pack(fill="both", expand=True)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self._tab_general(notebook)
        self._tab_popup(notebook)
        self._tab_rules(notebook)
        self._tab_info(notebook)

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="취소 (Esc)", style="Set.TButton", command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="저장", style="Set.TButton", command=self._save).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())

    # ---- 탭 ----
    def _page(self, notebook, title):
        page = ttk.Frame(notebook, padding=16)
        notebook.add(page, text=f"  {title}  ")
        return page

    def _tab_general(self, nb):
        p = self._page(nb, "일반")
        ttk.Label(p, text="감지 대상 폴더", font=FONT_B).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(p, text="이 폴더에 새로 생기는 파일을 기록합니다. 변경하면 바로 적용됩니다.",
                  font=FONT, foreground=GRAY).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 6))
        self.path_var = tk.StringVar(value=str(self.current_dir()))
        ttk.Entry(p, textvariable=self.path_var, width=52, font=FONT).grid(
            row=2, column=0, columnspan=2, sticky="ew", ipady=3)
        ttk.Button(p, text="찾아보기...", style="Set.TButton", command=self._browse).grid(row=2, column=2, padx=(6, 0))
        ttk.Button(p, text="기본값(다운로드 폴더)", style="Set.TButton",
                   command=lambda: self.path_var.set(str(default_watch_dir()))).grid(
            row=3, column=0, sticky="w", pady=(6, 0))
        self.sub_var = tk.BooleanVar(value=self.settings.get("watch_subfolders"))
        ttk.Checkbutton(p, text="하위 폴더도 함께 감지 (압축을 풀면 파일마다 기록됩니다)", variable=self.sub_var,
                        style="Set.TCheckbutton").grid(row=3, column=1, columnspan=2, sticky="w",
                                                       padx=(12, 0), pady=(6, 0))

        ttk.Separator(p).grid(row=4, column=0, columnspan=3, sticky="ew", pady=14)
        self.autostart_var = tk.BooleanVar(value=self.is_autostart())
        ttk.Checkbutton(p, text="Windows를 시작할 때 자동으로 실행", variable=self.autostart_var,
                        style="Set.TCheckbutton").grid(row=5, column=0, columnspan=3, sticky="w")

        ttk.Separator(p).grid(row=6, column=0, columnspan=3, sticky="ew", pady=14)
        ttk.Label(p, text="목록 글자 크기", font=FONT_B).grid(row=7, column=0, sticky="w")
        current = self.settings.get("list_font_size")
        label = next((k for k, v in FONT_SIZES.items() if v == current), "크게")
        self.font_var = tk.StringVar(value=label)
        ttk.Combobox(p, values=list(FONT_SIZES), textvariable=self.font_var, width=10,
                     state="readonly", font=FONT).grid(row=7, column=1, sticky="w", padx=(8, 0))

    def _tab_popup(self, nb):
        p = self._page(nb, "팝업")
        ttk.Label(p, text="파일을 받았을 때", font=FONT_B).grid(row=0, column=0, columnspan=2, sticky="w")
        self.mode_var = tk.StringVar(value=self.settings.get("popup_mode"))
        for i, (value, text) in enumerate(POPUP_MODE_LABELS):
            ttk.Radiobutton(p, text=text, value=value, variable=self.mode_var,
                            style="Set.TRadiobutton").grid(row=1 + i, column=0, columnspan=2, sticky="w", pady=1)
        seconds = self.settings.get("autoskip_seconds")
        self.auto_var = tk.BooleanVar(value=seconds > 0)
        self.secs_var = tk.IntVar(value=seconds if seconds > 0 else 30)
        row = ttk.Frame(p)
        row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(row, text="입력이 없으면 자동으로 건너뛰기:", variable=self.auto_var,
                        style="Set.TCheckbutton").pack(side="left")
        ttk.Spinbox(row, from_=5, to=600, width=5, textvariable=self.secs_var, font=FONT).pack(side="left", padx=6)
        ttk.Label(row, text="초 후", font=FONT).pack(side="left")

        ttk.Separator(p).grid(row=5, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(p, text="목적 목록", font=FONT_B).grid(row=6, column=0, sticky="w")
        ttk.Label(p, text="팝업에서 고를 수 있는 목적입니다. 맨 위 항목이 처음 기본값입니다.",
                  font=FONT, foreground=GRAY).grid(row=7, column=0, columnspan=2, sticky="w")
        self.purposes_editor = ListEditor(p, reorder=True)
        self.purposes_editor.grid(row=8, column=0, sticky="ew", pady=(6, 0))
        self.purposes_editor.set_items(self.settings.purposes)
        ttk.Button(p, text="기본 목록으로", style="Set.TButton",
                   command=lambda: self.purposes_editor.set_items(DEFAULT_PURPOSES)).grid(
            row=8, column=1, sticky="n", padx=(8, 0), pady=(6, 0))

    def _tab_rules(self, nb):
        p = self._page(nb, "제외 규칙")
        ttk.Label(p, text="아래 조건에 맞는 파일은 기록만 하고 입력창은 띄우지 않습니다.",
                  font=FONT, foreground=GRAY).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(p, text="이 크기보다 작은 파일", font=FONT_B).grid(row=1, column=0, sticky="w", pady=(12, 0))
        row = ttk.Frame(p)
        row.grid(row=2, column=0, columnspan=2, sticky="w")
        self.minsize_var = tk.StringVar(value=f"{self.settings.get('min_size_mb'):g}")
        ttk.Spinbox(row, from_=0, to=10000, increment=1, width=7, textvariable=self.minsize_var,
                    font=FONT).pack(side="left")
        ttk.Label(row, text="MB  (0이면 사용 안 함)", font=FONT).pack(side="left", padx=6)

        ttk.Label(p, text="제외할 확장자", font=FONT_B).grid(row=3, column=0, sticky="w", pady=(14, 0))
        ttk.Label(p, text="예: png, jpg", font=FONT, foreground=GRAY).grid(row=3, column=1, sticky="w", pady=(14, 0))
        self.exts_editor = ListEditor(p, normalize=normalize_ext, height=5)
        self.exts_editor.grid(row=4, column=0, sticky="ew", padx=(0, 10))
        self.exts_editor.set_items(self.settings.get("exclude_exts"))
        ttk.Label(p, text="제외할 사이트", font=FONT_B).grid(row=3, column=2, sticky="w", pady=(14, 0), padx=(10, 0))
        self.domains_editor = ListEditor(p, normalize=normalize_domain, height=5)
        self.domains_editor.grid(row=4, column=2, sticky="ew", padx=(10, 0))
        self.domains_editor.set_items(self.settings.get("exclude_domains"))
        ttk.Label(p, text="팝업의 '이 사이트는 다시 묻지 않기'를 체크해도 여기에 추가됩니다.",
                  font=FONT, foreground=GRAY).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _tab_info(self, nb):
        p = self._page(nb, "정보")
        db_path = self.data_dir / "catalog.db"
        size = db_path.stat().st_size if db_path.exists() else 0
        rows = (("프로그램 버전", __version__), ("개발자", f"{DEVELOPER_NAME} ({DEVELOPER_EMAIL})"),
                ("기록 개수", f"{self.db.count_all()}건"),
                ("목적 안 쓴 기록", f"{self.db.count_unfilled()}건"),
                ("기록 파일 크기", human_size(size)), ("데이터 폴더", str(self.data_dir)))
        for i, (k, v) in enumerate(rows):
            ttk.Label(p, text=k, font=FONT_B).grid(row=i, column=0, sticky="nw", pady=2, padx=(0, 16))
            if k == "개발자":
                self._developer_cell(p).grid(row=i, column=1, sticky="w", pady=2)
                continue
            ttk.Label(p, text=v, font=FONT, wraplength=420).grid(row=i, column=1, sticky="w", pady=2)
        bar = ttk.Frame(p)
        bar.grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(16, 0))
        ttk.Button(bar, text="데이터 폴더 열기", style="Set.TButton",
                   command=lambda: os.startfile(self.data_dir)).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="오류 기록 열기", style="Set.TButton", command=self._open_log).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="기록 백업 만들기...", style="Set.TButton", command=self._backup).pack(side="left")

    def _developer_cell(self, parent):
        """'일등감자 (메일주소)' — 메일 주소를 누르면 기본 메일 프로그램으로 새 메일 쓰기 창이 열린다."""
        cell = ttk.Frame(parent)
        bg = ttk.Style(self.root).lookup("TFrame", "background") or self.root.cget("bg")
        ttk.Label(cell, text=f"{DEVELOPER_NAME} (", font=FONT, padding=0).pack(side="left")
        self.mail_link = tk.Label(cell, text=DEVELOPER_EMAIL, font=("Malgun Gothic", 11, "underline"),
                                  fg="#2563eb", bg=bg, cursor="hand2")
        self.mail_link.pack(side="left")
        ttk.Label(cell, text=")", font=FONT, padding=0).pack(side="left")
        self.mail_link.bind("<Button-1>", lambda _e: self.send_mail())
        self.mail_link.bind("<Enter>", lambda _e: self.mail_link.config(fg="#1e40af"))
        self.mail_link.bind("<Leave>", lambda _e: self.mail_link.config(fg="#2563eb"))
        return cell

    def send_mail(self):
        """기본 메일 프로그램으로 개발자에게 보내는 새 메일을 연다. 메일 프로그램이 없으면 주소를 복사해 준다."""
        subject = quote(f"Download Catalog 문의 (v{__version__})")
        try:
            os.startfile(f"mailto:{DEVELOPER_EMAIL}?subject={subject}")
        except OSError:
            self.root.clipboard_clear()
            self.root.clipboard_append(DEVELOPER_EMAIL)
            messagebox.showinfo("메일 보내기",
                                f"기본 메일 프로그램을 열 수 없어 주소를 복사했습니다.\n{DEVELOPER_EMAIL}",
                                parent=self.win)

    # ---- 동작 ----
    def _browse(self):
        chosen = filedialog.askdirectory(parent=self.win, initialdir=self.path_var.get() or None,
                                         title="감지할 폴더 선택", mustexist=True)
        if chosen:
            self.path_var.set(str(Path(chosen)))

    def _open_log(self):
        log = self.data_dir / "error.log"
        if log.exists():
            os.startfile(log)
        else:
            messagebox.showinfo("오류 기록", "기록된 오류가 없습니다.", parent=self.win)

    def _backup(self):
        from datetime import datetime
        dest = filedialog.asksaveasfilename(
            parent=self.win, title="기록 백업 저장", defaultextension=".db",
            initialfile=f"catalog-backup-{datetime.now():%Y%m%d}.db", filetypes=[("기록 파일", "*.db")])
        if dest:
            self.db.backup_to(dest)
            messagebox.showinfo("백업", f"저장했습니다.\n{dest}", parent=self.win)

    def collect(self):
        """화면의 값을 검사해서 dict로. 잘못된 값이면 (None, 오류 문구)."""
        folder = Path(self.path_var.get().strip().strip('"'))
        if not folder.is_dir():
            return None, f"폴더를 찾을 수 없습니다.\n{folder}"
        try:
            min_mb = float(self.minsize_var.get() or 0)
            if min_mb < 0:
                raise ValueError
        except ValueError:
            return None, "크기는 0 이상의 숫자로 입력해 주세요."
        try:
            seconds = int(self.secs_var.get()) if self.auto_var.get() else 0
            if self.auto_var.get() and not 5 <= seconds <= 600:
                raise ValueError
        except (ValueError, tk.TclError):
            return None, "자동 건너뛰기 시간은 5~600초로 입력해 주세요."
        purposes = self.purposes_editor.items()
        if not purposes:
            return None, "목적 목록이 비어 있습니다. 하나 이상 있어야 합니다."
        return {
            "watch_dir": folder,
            "watch_subfolders": self.sub_var.get(),
            "autostart": self.autostart_var.get(),
            "list_font_size": FONT_SIZES.get(self.font_var.get(), 12),
            "popup_mode": self.mode_var.get(),
            "autoskip_seconds": seconds,
            "purposes": purposes,
            "min_size_mb": min_mb,
            "exclude_exts": self.exts_editor.items(),
            "exclude_domains": self.domains_editor.items(),
        }, None

    def _save(self):
        values, error = self.collect()
        if error:
            messagebox.showerror("설정 확인", error, parent=self.win)
            return
        try:
            self.on_apply(values)
        except Exception as e:
            messagebox.showerror("적용 실패", f"설정을 적용하지 못했습니다.\n{e}", parent=self.win)
            return
        self.win.destroy()

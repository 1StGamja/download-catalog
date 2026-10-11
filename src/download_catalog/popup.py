"""목적·메모 입력 팝업. 여러 건이 연달아 와도 하나씩 순서대로 보여 준다.

설정(popup_mode)에 따라 바로 팝업을 띄우거나(popup), 작은 알림만 보여 주고 클릭했을 때만
입력창을 열거나(quiet), 아무것도 띄우지 않는다(off).
"""
import ctypes
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import ttk

from .urlutil import domain_of, human_size

# 기본(약 9pt)의 1.5배 크기
FONT = ("Malgun Gothic", 14)
FONT_TITLE = ("Malgun Gothic", 17, "bold")
FONT_SMALL = ("Malgun Gothic", 12)
WRAP = 570

BANNER_COLORS = {"duplicate": ("#fef3c7", "#92400e"), "new_version": ("#dbeafe", "#1e40af")}
TYPE_COLORS = {"#2563eb": ("zip", "rar", "7z", "gz", "tar", "iso"),
               "#dc2626": ("pdf",),
               "#16a34a": ("xls", "xlsx", "csv"),
               "#ea580c": ("ppt", "pptx"),
               "#7c3aed": ("png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"),
               "#0891b2": ("doc", "docx", "hwp", "hwpx", "txt", "md"),
               "#475569": ("exe", "msi", "dmg", "apk")}


def type_badge(file_name):
    """(표시 글자, 배경색): 파일 종류를 색깔 배지로 보여 주기 위한 값."""
    ext = Path(file_name).suffix.lower().lstrip(".")
    for color, exts in TYPE_COLORS.items():
        if ext in exts:
            return ext.upper()[:5], color
    return (ext.upper()[:5] or "파일"), "#64748b"


def _focus(win, widget):
    """팝업을 맨 앞으로 가져와 widget에 커서를 둔다.

    윈도우는 백그라운드 프로그램이 포커스를 가져가는 것을 막으므로, 입력 이벤트를 하나
    흉내 내어 이 제한을 풀고 SetForegroundWindow를 호출한다(실패해도 무시).
    Alt 키는 쓰지 않는다: 눌렀다 떼면 시스템 메뉴 모드가 되어 Tk 이벤트 루프가 멈출 수 있다.
    """
    if not win.winfo_exists():
        return
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(0x87, 0, 0, 0)       # F24 누름(어떤 프로그램도 쓰지 않는 키)
        user32.keybd_event(0x87, 0, 2, 0)       # F24 뗌
        user32.SetForegroundWindow(user32.GetParent(win.winfo_id()))
    except Exception:
        pass
    win.lift()
    win.focus_force()
    widget.focus_set()
    widget.icursor("end")  # Entry·Combobox 공통


def describe(row, kind, related):
    """팝업 상단에 보여 줄 안내 문구."""
    if kind == "duplicate" and related is not None:
        return f"이미 받은 파일입니다 ({related['downloaded_at'][:10]}, {related['file_name']})"
    if kind == "new_version" and related is not None:
        return (f"새 버전입니다 → v{row['version']}  "
                f"(이전: {related['file_name']}, {related['downloaded_at'][:10]})")
    return "새 파일입니다"


def suggest_note(db, settings, row):
    """입력 칸에 미리 채울 (목적, 메모, 안내문구). 같은 사이트 → 마지막 목적 → 첫 번째 목적 순."""
    note = db.last_note_for_domain(row["domain"])
    if note:
        return note[0], note[1], f"※ {row['domain']}에서 지난번에: {note[0]}"
    last = db.last_purpose()
    if last:
        return last, "", ""
    return settings.purposes[0], "", ""


class PopupManager:
    def __init__(self, root, db, settings, toast, on_change=None, on_exclude_domain=None):
        self.root, self.db, self.settings, self.toast = root, db, settings, toast
        self.on_change = on_change or (lambda: None)
        self.on_exclude_domain = on_exclude_domain or (lambda domain: None)
        self._queue = deque()
        self._quiet_pending = []
        self._current = None
        self._update_rest_button = None   # 열려 있는 팝업의 '나머지 N개' 버튼 갱신 함수
        self._styled = False

    # ---- 들어오는 새 기록 ----
    def notify(self, record_id, kind, related):
        mode = self.settings.get("popup_mode")
        if mode == "popup":
            self.enqueue(record_id, kind, related)
        elif mode == "quiet":
            self._quiet_pending.append((record_id, kind, related))
            self._show_quiet_toast()

    def _show_quiet_toast(self):
        n = len(self._quiet_pending)
        if n == 1:
            row = self.db.get(self._quiet_pending[0][0])
            kind = self._quiet_pending[0][1]
            label = {"duplicate": "이미 받은 파일", "new_version": "새 버전"}.get(kind, "새 파일")
            text = f"{row['file_name'] if row else ''}\n기록했어요 ({label})"
        else:
            text = f"새 파일 {n}개를 기록했어요"
        self.toast.show(text, on_click=self.open_pending, hint="클릭하면 목적을 입력합니다")

    def open_pending(self):
        """조용히 알림으로 쌓인 기록을 입력 팝업으로 연다."""
        pending, self._quiet_pending = self._quiet_pending, []
        for item in pending:
            self.enqueue(*item)

    def enqueue(self, record_id, kind, related):
        self._queue.append((record_id, kind, related))
        if self._current is None:
            self._show_next()
        elif self._update_rest_button:
            self._update_rest_button()   # 이미 열린 팝업에 '나머지 N개도…' 버튼을 나타내거나 개수를 갱신

    # ---- 화면 ----
    def _show_next(self):
        if not self._queue:
            self._current = None
            return
        record_id, kind, related = self._queue.popleft()
        row = self.db.get(record_id)
        if row is None:
            self._show_next()
            return
        self._current = self._build(row, kind, related)

    def _finish(self, win):
        win.destroy()
        self._current = None
        self._update_rest_button = None
        self.on_change()
        self.root.after(200, self._show_next)

    def _ensure_styles(self):
        if self._styled:
            return
        style = ttk.Style(self.root)
        style.configure("Pop.TButton", font=FONT, padding=(14, 6))
        style.configure("Pop.TCheckbutton", font=FONT_SMALL)
        self.root.option_add("*TCombobox*Listbox.font", FONT)
        self._styled = True

    def _build(self, row, kind, related):
        self._ensure_styles()
        win = tk.Toplevel(self.root)
        win.title("Download Catalog")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=18)
        frame.grid(sticky="nsew")
        domain = row["domain"] or domain_of(row["source_url"]) or domain_of(row["referrer_url"])

        # 제목: 종류 배지 + 파일명
        head = ttk.Frame(frame)
        head.grid(row=0, column=0, columnspan=2, sticky="w")
        badge_text, badge_color = type_badge(row["file_name"])
        tk.Label(head, text=badge_text, font=("Malgun Gothic", 10, "bold"), fg="white",
                 bg=badge_color, padx=6, pady=2).pack(side="left", padx=(0, 8))
        ttk.Label(head, text=row["file_name"], font=FONT_TITLE, wraplength=WRAP - 90).pack(side="left")

        # 안내(새 파일 / 새 버전 / 중복)는 눈에 띄는 색 배경
        bg, fg = BANNER_COLORS.get(kind, (None, "#374151"))
        banner = tk.Label(frame, text=describe(row, kind, related), font=FONT, fg=fg,
                          bg=bg or win.cget("bg"), wraplength=WRAP, justify="left",
                          padx=8 if bg else 0, pady=4 if bg else 0, anchor="w")
        banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # 크기 · 도메인 + 자세히
        full_url = row["source_url"] or row["referrer_url"]
        info = ttk.Frame(frame)
        info.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(info, text=f"{human_size(row['size'])} · {domain or '출처를 알 수 없음'}",
                  font=FONT_SMALL, foreground="#555").pack(side="left")
        url_label = ttk.Label(frame, text=full_url or "", font=("Malgun Gothic", 10),
                              foreground="#555", wraplength=WRAP)
        if full_url:
            toggle = tk.Label(info, text="자세히 ▾", font=("Malgun Gothic", 10, "underline"),
                              fg="#2563eb", cursor="hand2")
            toggle.pack(side="left", padx=(8, 0))

            def flip(_e=None):
                if url_label.winfo_ismapped():
                    url_label.grid_remove()
                    toggle.config(text="자세히 ▾")
                else:
                    url_label.grid(row=3, column=0, columnspan=2, sticky="w")
                    toggle.config(text="접기 ▴")
                win.update_idletasks()

            toggle.bind("<Button-1>", flip)

        # 입력 제안
        purpose_default, memo_default, hint = suggest_note(self.db, self.settings, row)
        row_n = 4
        if hint:
            ttk.Label(frame, text=hint, font=FONT_SMALL, foreground="#2563eb").grid(
                row=row_n, column=0, columnspan=2, sticky="w", pady=(8, 0))
            row_n += 1
        values = list(self.settings.purposes)
        if purpose_default not in values:
            values.insert(0, purpose_default)
        ttk.Label(frame, text="목적", font=FONT).grid(row=row_n, column=0, sticky="w", padx=(0, 8))
        purpose = ttk.Combobox(frame, values=values, width=45, font=FONT)
        purpose.grid(row=row_n, column=1, sticky="ew", pady=4, ipady=5)
        purpose.set(purpose_default)
        ttk.Label(frame, text="메모", font=FONT).grid(row=row_n + 1, column=0, sticky="w", padx=(0, 8))
        memo = ttk.Entry(frame, width=50, font=FONT)
        memo.grid(row=row_n + 1, column=1, sticky="ew", pady=4, ipady=5)
        if memo_default:
            memo.insert(0, memo_default)
            memo.select_range(0, "end")   # 그냥 입력하면 덮어쓰고, Enter면 그대로 사용

        exclude_var = tk.BooleanVar(value=False)
        if domain:
            ttk.Checkbutton(frame, text=f"{domain} 사이트는 다시 묻지 않기", variable=exclude_var,
                            style="Pop.TCheckbutton").grid(row=row_n + 2, column=1, sticky="w")

        countdown = ttk.Label(frame, text="", font=FONT_SMALL, foreground="#b45309")
        countdown.grid(row=row_n + 3, column=0, columnspan=2, sticky="w")

        def apply_exclude():
            if exclude_var.get() and domain:
                self.on_exclude_domain(domain)

        def save(_event=None):
            self.db.update_note(row["id"], purpose.get().strip(), memo.get().strip())
            apply_exclude()
            self._finish(win)

        def save_all():
            p = purpose.get().strip()
            self.db.update_note(row["id"], p, memo.get().strip())
            if p:
                self.db.update_purpose_many([item[0] for item in self._queue], p)
            self._queue.clear()
            apply_exclude()
            self._finish(win)

        def skip(_event=None):
            apply_exclude()
            self._finish(win)

        def remove():
            self.db.delete(row["id"])
            self._finish(win)

        buttons = ttk.Frame(frame)
        buttons.grid(row=row_n + 4, column=0, columnspan=2, sticky="e", pady=(14, 0))
        rest_button = ttk.Button(buttons, style="Pop.TButton", command=save_all)
        fixed = []
        if kind == "duplicate":
            fixed.append(ttk.Button(buttons, text="기록 삭제", style="Pop.TButton", command=remove))
        fixed.append(ttk.Button(buttons, text="건너뛰기 (Esc)", style="Pop.TButton", command=skip))
        fixed.append(ttk.Button(buttons, text="저장 (Enter)", style="Pop.TButton", command=save))

        def update_rest_button():
            """대기 중인 파일 수에 맞춰 '나머지 N개도 같은 목적으로' 버튼을 나타내거나 숨긴다."""
            if not win.winfo_exists():
                return
            n = len(self._queue)
            for b in (rest_button, *fixed):
                b.pack_forget()
            if n:
                rest_button.config(text=f"나머지 {n}개도 같은 목적으로")
                rest_button.pack(side="left", padx=3)
            for b in fixed:
                b.pack(side="left", padx=3)
            self._place(win)

        self._update_rest_button = update_rest_button
        update_rest_button()
        win.bind("<Return>", save)
        win.bind("<Escape>", skip)
        win.protocol("WM_DELETE_WINDOW", skip)

        # 일정 시간 입력이 없으면 자동으로 건너뛰기(설정). 키보드·마우스를 쓰면 취소된다.
        seconds = self.settings.get("autoskip_seconds")
        if seconds > 0:
            state = {"left": seconds, "active": True}

            def tick():
                if not state["active"] or not win.winfo_exists():
                    return
                if state["left"] <= 0:
                    skip()
                    return
                countdown.config(text=f"{state['left']}초 후 자동으로 건너뜁니다")
                state["left"] -= 1
                win.after(1000, tick)

            def cancel(e=None):
                if e is not None and getattr(e, "keysym", "") == "F24":
                    return   # 포커스를 가져오려고 우리가 보낸 가짜 키는 사용자 입력이 아니다
                state["active"] = False
                if win.winfo_exists():
                    countdown.config(text="")

            win.bind("<Key>", cancel, add="+")
            win.bind("<Button-1>", cancel, add="+")
            tick()

        self._place(win)
        win.after(100, lambda: _focus(win, memo))
        return win

    @staticmethod
    def _place(win):
        """화면 오른쪽 아래 모서리에 놓는다(내용이 바뀌어 크기가 달라져도 모서리 기준 유지)."""
        win.update_idletasks()
        x = win.winfo_screenwidth() - win.winfo_reqwidth() - 20
        y = win.winfo_screenheight() - win.winfo_reqheight() - 70
        win.geometry(f"+{x}+{y}")

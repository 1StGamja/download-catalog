"""기록 목록·검색 창(정렬, 필터, 우클릭 메뉴, 단축키, 여러 건 편집)."""
import os
import re
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

from .urlutil import human_size

COLUMNS = (   # (키, 제목, 기본 너비, 정렬)
    ("downloaded_at", "받은 시각", 150, "w"),
    ("file_name", "파일명", 240, "w"),
    ("version", "버전", 55, "center"),
    ("purpose", "목적", 100, "w"),
    ("memo", "메모", 200, "w"),
    ("domain", "도메인", 200, "w"),
    ("size", "크기", 85, "e"),
    ("status", "상태", 60, "center"),
)
PERIODS = (("전체 기간", None), ("오늘", 0), ("최근 7일", 7), ("최근 30일", 30))
ALL_PURPOSES = "전체 목적"
DEFAULT_GEOMETRY = "1200x600"


def safe_geometry(geometry, screen_w, screen_h):
    """저장된 창 위치가 지금 화면 밖이면(모니터를 뗀 경우 등) 위치는 버리고 크기만 쓴다."""
    m = re.fullmatch(r"(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?", geometry or "")
    if not m:
        return DEFAULT_GEOMETRY
    w, h = int(m[1]), int(m[2])
    w, h = min(w, screen_w), min(h, screen_h)
    if m[3] is None:
        return f"{w}x{h}"
    x, y = int(m[3]), int(m[4])
    if x < -50 or y < -50 or x > screen_w - 100 or y > screen_h - 100:
        return f"{w}x{h}"
    return f"{w}x{h}{x:+d}{y:+d}"


def open_in_explorer(path):
    """파일이 있으면 탐색기에서 그 파일을 선택해 열고, 없으면 폴더만 연다."""
    if os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        folder = os.path.dirname(path)
        if os.path.isdir(folder):
            os.startfile(folder)


class NoteDialog:
    """목적·메모 수정 창. 여러 건을 고른 경우에는 목적만(선택하면 메모도) 한꺼번에 바꾼다."""

    def __init__(self, parent, purposes, purpose="", memo="", count=1, on_ok=None):
        self.on_ok, self.count = on_ok, count
        win = self.win = tk.Toplevel(parent)
        win.title("목적/메모 수정" if count == 1 else f"{count}개 기록의 목적 한꺼번에 바꾸기")
        win.transient(parent)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=14)
        f.pack()
        font = ("Malgun Gothic", 11)
        ttk.Label(f, text="목적", font=font).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.purpose = ttk.Combobox(f, values=purposes, width=38, font=font)
        self.purpose.grid(row=0, column=1, pady=3, ipady=3)
        self.purpose.set(purpose)
        ttk.Label(f, text="메모", font=font).grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.memo = ttk.Entry(f, width=41, font=font)
        self.memo.grid(row=1, column=1, pady=3, ipady=3)
        self.memo.insert(0, memo)
        self.change_memo = tk.BooleanVar(value=(count == 1))
        if count > 1:
            self.memo.config(state="disabled")
            ttk.Checkbutton(f, text="메모도 같은 내용으로 바꾸기", variable=self.change_memo,
                            command=self._toggle_memo).grid(row=2, column=1, sticky="w")
        row = ttk.Frame(f)
        row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(row, text="취소 (Esc)", command=win.destroy).pack(side="left", padx=3)
        ttk.Button(row, text="저장 (Enter)", command=self._ok).pack(side="left", padx=3)
        win.bind("<Return>", lambda _e: self._ok())
        win.bind("<Escape>", lambda _e: win.destroy())
        (self.purpose if count > 1 else self.memo).focus_set()
        win.grab_set()

    def _toggle_memo(self):
        self.memo.config(state="normal" if self.change_memo.get() else "disabled")

    def _ok(self):
        purpose = self.purpose.get().strip()   # 창을 닫기 전에 값을 읽는다(닫으면 위젯이 사라짐)
        memo = self.memo.get().strip() if self.change_memo.get() else None
        self.win.destroy()
        if self.on_ok:
            self.on_ok(purpose, memo)


class CatalogWindow:
    def __init__(self, root, db, settings):
        self.root, self.db, self.settings = root, db, settings
        self.win = None
        self.on_settings = None     # 환경설정 창을 여는 함수(main이 연결)
        self.on_review = None       # '하나씩 입력' 창을 여는 함수(main이 연결)
        self.on_change = lambda: None
        self._rows = {}
        self._tip = None
        self._tip_after = None
        self._tip_key = None

    # ---- 창 만들기 ----
    def show(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.refresh()
            return
        state = self.settings.get("catalog")
        self.sort_key, self.sort_desc = state["sort"][0], bool(state["sort"][1])
        if self.sort_key not in {c[0] for c in COLUMNS}:
            self.sort_key, self.sort_desc = "downloaded_at", True
        self.win = win = tk.Toplevel(self.root)
        win.title("Download Catalog - 다운로드 기록")
        win.geometry(safe_geometry(state["geometry"], win.winfo_screenwidth(), win.winfo_screenheight()))
        win.protocol("WM_DELETE_WINDOW", self.close)
        size = self.settings.get("list_font_size")
        style = ttk.Style(self.root)
        style.configure("Cat.Treeview", font=("Malgun Gothic", size), rowheight=int(size * 2.4))
        style.configure("Cat.Treeview.Heading", font=("Malgun Gothic", size, "bold"))
        self._build_filters()
        self._build_banner()
        self._build_tree(state)
        self._build_status()
        self._build_menu()
        self._bind_keys()
        self.refresh()
        self.search_entry.focus_set()

    def _build_filters(self):
        win = self.win
        bar = ttk.Frame(win, padding=(8, 8, 8, 2))
        bar.pack(fill="x")
        ttk.Label(bar, text="검색").pack(side="left")
        self.query = tk.StringVar()
        self.search_entry = ttk.Entry(bar, textvariable=self.query, width=28)
        self.search_entry.pack(side="left", padx=(6, 12), ipady=2)
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh())
        self.period = ttk.Combobox(bar, values=[p[0] for p in PERIODS], width=10, state="readonly")
        self.period.set(PERIODS[0][0])
        self.period.pack(side="left", padx=3)
        self.purpose_filter = ttk.Combobox(bar, values=[ALL_PURPOSES], width=14, state="readonly")
        self.purpose_filter.set(ALL_PURPOSES)
        self.purpose_filter.pack(side="left", padx=3)
        for c in (self.period, self.purpose_filter):
            c.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.only_unfilled = tk.BooleanVar(value=False)
        self.only_new_version = tk.BooleanVar(value=False)
        self.hide_dups = tk.BooleanVar(value=False)
        for text, var in (("미입력만", self.only_unfilled), ("새 버전만", self.only_new_version),
                          ("중복 제외", self.hide_dups)):
            ttk.Checkbutton(bar, text=text, variable=var, command=self.refresh).pack(side="left", padx=4)
        if self.on_settings:
            ttk.Button(bar, text="환경설정", command=self.on_settings).pack(side="right", padx=(6, 0))

        actions = ttk.Frame(win, padding=(8, 2, 8, 4))
        actions.pack(fill="x")
        self.actions = actions
        for text, cmd in (("파일 열기", self.open_file), ("폴더 열기", self.open_folder),
                          ("목적/메모 수정", self.edit_selected), ("기록 삭제", self.delete_selected)):
            ttk.Button(actions, text=text, command=cmd).pack(side="left", padx=(0, 6))

    def _build_banner(self):
        self.banner = tk.Frame(self.win, bg="#fef3c7")
        self.banner_label = tk.Label(self.banner, bg="#fef3c7", fg="#92400e",
                                     font=("Malgun Gothic", 10, "bold"))
        self.banner_label.pack(side="left", padx=10, pady=4)
        ttk.Button(self.banner, text="하나씩 입력", command=lambda: self.on_review and self.on_review()
                   ).pack(side="left", padx=4)
        ttk.Button(self.banner, text="이 기록만 보기", command=self._show_unfilled_only).pack(side="left")

    def _build_tree(self, state):
        frame = ttk.Frame(self.win)
        frame.pack(fill="both", expand=True, padx=8)
        self.tree_frame = frame
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in COLUMNS], show="headings",
                                 style="Cat.Treeview", selectmode="extended")
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=int(state["widths"].get(key, width)), anchor=anchor, minwidth=40)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("missing", foreground="#9ca3af")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_status())
        self.tree.bind("<Double-1>", lambda _e: self.open_file())
        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Leave>", lambda _e: self._hide_tip())

    def _build_status(self):
        self.status = tk.StringVar()
        ttk.Label(self.win, textvariable=self.status, padding=(10, 4), foreground="#555").pack(fill="x")

    def _build_menu(self):
        m = self.menu = tk.Menu(self.win, tearoff=False)
        m.add_command(label="파일 열기 (Enter)", command=self.open_file)
        m.add_command(label="폴더 열기", command=self.open_folder)
        m.add_command(label="주소 복사", command=self.copy_url)
        m.add_separator()
        m.add_command(label="목적/메모 수정", command=self.edit_selected)
        m.add_separator()
        m.add_command(label="기록 삭제 (Delete)", command=self.delete_selected)
        self.tree.bind("<Button-3>", self._popup_menu)

    def _bind_keys(self):
        t, w = self.tree, self.win
        t.bind("<Delete>", lambda _e: self.delete_selected())
        t.bind("<Return>", lambda _e: self.open_file())
        t.bind("<Control-a>", self._select_all)
        t.bind("<Control-A>", self._select_all)
        w.bind("<Control-f>", self._focus_search)
        w.bind("<Control-F>", self._focus_search)
        self.search_entry.bind("<Escape>", self._clear_search)
        self.search_entry.bind("<Down>", lambda _e: (t.focus_set(), self._focus_first()))

    # ---- 데이터 표시 ----
    def close(self):
        if self.win is None or not self.win.winfo_exists():
            return
        try:
            self.settings.set("catalog", {
                "geometry": self.win.geometry(),
                "widths": {c[0]: int(self.tree.column(c[0], "width")) for c in COLUMNS},
                "sort": [self.sort_key, self.sort_desc],
            })
            self.settings.save()
        except Exception:
            pass
        self._hide_tip()
        self.win.destroy()
        self.win = None

    def alive(self):
        return self.win is not None and self.win.winfo_exists()

    def refresh(self):
        if not self.alive():
            return
        selected = set(self.tree.selection())
        days = dict(PERIODS)[self.period.get()]
        purpose = self.purpose_filter.get()
        rows = self.db.search(
            self.query.get(), days=days,
            purpose=None if purpose == ALL_PURPOSES else purpose,
            unfilled=self.only_unfilled.get(), new_version=self.only_new_version.get(),
            hide_duplicates=self.hide_dups.get())
        self._rows = {}
        entries = []
        for row in rows:
            status = "있음" if os.path.exists(row["file_path"]) else "없음"
            self._rows[str(row["id"])] = row
            entries.append((self._sort_value(row, status), row["id"], row, status))
        entries.sort(key=lambda e: (e[0], e[1]), reverse=self.sort_desc)
        self.tree.delete(*self.tree.get_children())
        for _v, _id, row, status in entries:
            tags = ("missing",) if status == "없음" else ()
            self.tree.insert("", "end", iid=str(row["id"]), tags=tags, values=self._display(row, status))
        keep = [i for i in selected if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        self._update_headings()
        self._update_purpose_choices()
        self._update_banner()
        self._update_status()

    def _sort_value(self, row, status):
        key = self.sort_key
        if key == "version":
            return row["version"]
        if key == "size":
            return row["size"] or 0
        if key == "status":
            return status
        return (row[key] or "").lower()

    @staticmethod
    def _display(row, status):
        name = row["file_name"] + (" (중복)" if row["duplicate_of"] else "")
        return (row["downloaded_at"], name, f"v{row['version']}", row["purpose"] or "",
                row["memo"] or "", row["domain"] or "", human_size(row["size"]), status)

    def sort_by(self, key):
        if key == self.sort_key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key in ("downloaded_at", "version", "size")
        self.refresh()

    def _update_headings(self):
        for key, title, _w, _a in COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if key == self.sort_key else ""
            self.tree.heading(key, text=title + arrow)

    def _update_purpose_choices(self):
        names = list(self.settings.purposes)
        names += [p for p in self.db.distinct_purposes() if p not in names]
        self.purpose_filter.config(values=[ALL_PURPOSES] + names)

    def _update_banner(self):
        n = self.db.count_unfilled()
        if n:
            self.banner_label.config(text=f"목적을 입력하지 않은 기록이 {n}건 있습니다")
            if not self.banner.winfo_ismapped():
                self.banner.pack(fill="x", padx=8, pady=(0, 4), before=self.tree_frame)
        elif self.banner.winfo_ismapped():
            self.banner.pack_forget()

    def _show_unfilled_only(self):
        self.only_unfilled.set(True)
        self.refresh()

    def _update_status(self):
        if not self.alive():
            return
        text = f"총 {self.db.count_all()}건 중 {len(self._rows)}건 표시"
        selected = len(self.tree.selection())
        if selected:
            text += f"  ·  {selected}건 선택"
        self.status.set(text)

    # ---- 선택·동작 ----
    def selected_rows(self):
        return [self._rows[i] for i in self.tree.selection() if i in self._rows]

    def _select_all(self, _event=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def _focus_first(self):
        items = self.tree.get_children()
        if items:
            self.tree.selection_set(items[0])
            self.tree.focus(items[0])
        return "break"

    def _focus_search(self, _event=None):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        return "break"

    def _clear_search(self, _event=None):
        if self.query.get():
            self.query.set("")
            self.refresh()

    def _popup_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item and item not in self.tree.selection():
            self.tree.selection_set(item)
        if self.tree.selection():
            self.menu.tk_popup(event.x_root, event.y_root)

    def open_file(self):
        rows = self.selected_rows()
        if not rows:
            return
        path = rows[0]["file_path"]
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showwarning("파일 없음", "파일이 이동되었거나 삭제되었습니다.", parent=self.win)

    def open_folder(self):
        rows = self.selected_rows()
        if rows:
            open_in_explorer(rows[0]["file_path"])

    def copy_url(self):
        rows = self.selected_rows()
        if not rows:
            return
        url = rows[0]["source_url"] or rows[0]["referrer_url"] or ""
        if not url:
            messagebox.showinfo("주소 없음", "이 기록에는 저장된 주소가 없습니다.", parent=self.win)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.status.set("주소를 복사했습니다")

    def delete_selected(self):
        ids = [r["id"] for r in self.selected_rows()]
        if not ids:
            return
        msg = f"선택한 {len(ids)}개 기록을 삭제할까요?" if len(ids) > 1 else "이 기록을 삭제할까요?"
        if messagebox.askyesno("기록 삭제", f"{msg}\n(파일은 삭제되지 않습니다)", parent=self.win):
            self.db.delete_many(ids)
            self.refresh()
            self.on_change()

    def edit_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        names = list(self.settings.purposes)
        names += [p for p in self.db.distinct_purposes() if p not in names]
        ids = [r["id"] for r in rows]

        def apply(purpose, memo):
            if len(ids) == 1:
                self.db.update_note(ids[0], purpose, memo if memo is not None else rows[0]["memo"])
            else:
                self.db.update_purpose_many(ids, purpose, memo)
            self.refresh()
            self.on_change()

        first = rows[0]
        NoteDialog(self.win, names, first["purpose"] if len(rows) == 1 else "",
                   first["memo"] or "" if len(rows) == 1 else "", count=len(rows), on_ok=apply)

    # ---- 마우스를 올리면 전체 내용 보기 ----
    def _tip_text(self, row, key):
        if key == "domain":
            return "\n".join(u for u in (row["source_url"], row["referrer_url"]) if u)
        if key == "file_name":
            return row["file_path"]
        if key == "memo":
            return row["memo"] or ""
        return ""

    def _on_motion(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        key = None
        if item and col:
            idx = int(col[1:]) - 1
            if 0 <= idx < len(COLUMNS):
                key = COLUMNS[idx][0]
        tip_key = (item, key)
        if tip_key == self._tip_key:
            return
        self._hide_tip()
        self._tip_key = tip_key
        row = self._rows.get(item)
        text = self._tip_text(row, key) if row and key else ""
        if text:
            self._tip_after = self.root.after(
                500, lambda: self._show_tip(text, self.root.winfo_pointerx() + 14, self.root.winfo_pointery() + 18))

    def _show_tip(self, text, x, y):
        self._hide_tip(keep_key=True)
        tip = self._tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=text, justify="left", wraplength=700, bg="#ffffe1", relief="solid",
                 borderwidth=1, padx=6, pady=3, font=("Malgun Gothic", 10)).pack()
        tip.geometry(f"+{x}+{y}")

    def _hide_tip(self, keep_key=False):
        if self._tip_after:
            try:
                self.root.after_cancel(self._tip_after)
            except tk.TclError:
                pass
            self._tip_after = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
        if not keep_key:
            self._tip_key = None

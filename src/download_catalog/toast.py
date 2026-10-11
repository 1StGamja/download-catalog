"""화면 오른쪽 아래에 잠깐 떴다 사라지는 작은 알림. 포커스를 가져가지 않는다."""
import ctypes
import tkinter as tk

FONT = ("Malgun Gothic", 12)
GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080


def _no_activate(win):
    """창을 눌러도, 뜰 때도 활성화(포커스 이동)되지 않게 한다(실패해도 무시)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except Exception:
        pass


class Toast:
    def __init__(self, root):
        self.root = root
        self.win = None
        self._after_id = None

    def show(self, text, on_click=None, seconds=10, hint="클릭하면 열립니다"):
        self.close()
        win = tk.Toplevel(self.root)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#1f2937", highlightthickness=1, highlightbackground="#3b82f6")
        label = tk.Label(win, text=text, font=FONT, fg="white", bg="#1f2937",
                         justify="left", wraplength=420, padx=16, pady=10)
        label.pack()
        if on_click and hint:
            tk.Label(win, text=hint, font=("Malgun Gothic", 9), fg="#93c5fd", bg="#1f2937",
                     padx=16).pack(anchor="w", pady=(0, 8))

        def clicked(_event=None):
            self.close()
            if on_click:
                on_click()

        for widget in (win, *win.winfo_children()):
            widget.bind("<Button-1>", clicked)
            widget.bind("<Button-3>", lambda _e: self.close())
        win.update_idletasks()
        x = win.winfo_screenwidth() - win.winfo_reqwidth() - 20
        y = win.winfo_screenheight() - win.winfo_reqheight() - 70
        win.geometry(f"+{x}+{y}")
        _no_activate(win)
        self._after_id = win.after(int(seconds * 1000), self.close)

    def close(self):
        if self.win is not None:
            try:
                if self._after_id:
                    self.win.after_cancel(self._after_id)
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self._after_id = None

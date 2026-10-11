"""Chrome의 '다른 이름으로 저장' 창에 표시된 파일명을 자동으로 바꾼다.

Chrome은 같은 이름이 있으면 `name (4).zip`을 제안한다. 이 창이 뜨면 파일명 칸의 값이
충돌 이름이고 원래 이름의 파일이 **창이 열려 있는 폴더**에 있을 때, `name_년-월-일-시분.zip`으로 바꿔 넣는다.
창이 열린 폴더는 창의 주소 표시줄 텍스트("주소: 드라이브:경로")에서 읽는다. 경로를 알 수 없는 특수 폴더
(문서 같은 라이브러리)일 때는 감지 폴더 전체에서 같은 이름을 찾아 판단한다.
저장 버튼은 누르지 않는다(사용자가 확인 후 저장).
"""
import ctypes
import os
import re
import threading
import time
from ctypes import wintypes
from pathlib import Path

from . import versioning
from .recorder import collided_with_existing, timestamped_path

DIALOG_TITLES = ("다른 이름으로 저장", "Save As", "Save as")
FILENAME_COMBO_ID = 0x047C   # 구형 저장 창의 '파일 이름' 콤보박스 컨트롤 ID
EDIT_CTRL_ID = 1001          # 현대식 저장 창의 파일명 Edit 컨트롤 ID
WM_GETTEXT, WM_SETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000C, 0x000E
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ADDRESS_WAIT_TRIES = 8           # 주소를 읽지 못할 때 기다리는 횟수(약 2초) 후 감지 폴더 전체에서 찾는 방식으로 전환

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetDlgItem.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_ENUM, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, _ENUM, wintypes.LPARAM]


ADDRESS_PREFIXES = ("주소: ", "Address: ")   # 저장 창 주소 표시줄(ToolbarWindow32)의 이름 앞부분
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def parse_address_text(text):
    """저장 창 주소 표시줄 텍스트에서 폴더 경로를 읽는다. 경로가 아닌 표시 이름(예: '주소: 문서')이면 None."""
    for prefix in ADDRESS_PREFIXES:
        if (text or "").startswith(prefix):
            value = text[len(prefix):].strip()
            if _DRIVE_PATH.match(value) or value.startswith("\\\\"):
                return Path(value)
    return None


def exists_in_tree(root, filename, budget=1.0):
    """root 아래(하위 폴더 포함, '.'으로 시작하는 폴더 제외)에 같은 이름의 파일이 있는지. 시간 제한 있음."""
    target = filename.lower()
    deadline = time.monotonic() + budget
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if any(f.lower() == target for f in filenames):
            return True
        if time.monotonic() > deadline:
            return False
    return False


def suggest_name(current_text, folder, now=None, search_tree=False):
    """저장 창의 현재 파일명 -> 바꿀 이름. 바꿀 필요가 없으면 None.

    folder: 저장 창이 열려 있는 폴더. search_tree=True면 창의 폴더를 모를 때를 위해
    folder 전체(하위 폴더 포함)에서 원래 이름의 파일이 있는지 찾는다.
    """
    name = (current_text or "").strip()
    if not name or any(c in name for c in "\\/:"):
        return None
    path = Path(folder) / name
    if search_tree:
        stem = versioning.strip_copy_number(path.stem)
        if stem == path.stem:
            return None
        original = stem + path.suffix
        if not (path.with_name(original).exists() or exists_in_tree(folder, original)):
            return None
    elif not collided_with_existing(path):
        return None
    return timestamped_path(path, now).name


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _process_name(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def find_save_dialogs(process_names):
    """보이는 '다른 이름으로 저장' 창 중 지정한 프로세스 소유의 hwnd 목록."""
    found = []

    def cb(hwnd, _lparam):
        if (user32.IsWindowVisible(hwnd) and _class_name(hwnd) == "#32770"
                and _window_text(hwnd) in DIALOG_TITLES
                and _process_name(hwnd) in process_names):
            found.append(hwnd)
        return True

    user32.EnumWindows(_ENUM(cb), 0)
    return found


def find_filename_edit(dialog):
    """저장 창의 '파일 이름' 입력칸(Edit) 핸들. 없으면 None."""
    # 현대식 저장 창은 입력칸이 DirectUI 안쪽의 ComboBox(자식 Edit, 컨트롤 ID 1001)에 있다.
    # 구형 레이아웃은 최상위 컨트롤 0x47C(콤보) 아래에 있으므로 그쪽도 허용한다.
    edits = []
    legacy_combo = user32.GetDlgItem(dialog, FILENAME_COMBO_ID)

    def cb(hwnd, _lparam):
        if _class_name(hwnd) != "Edit":
            return True
        parent = user32.GetParent(hwnd)
        if _class_name(parent) == "ComboBox" and (
                user32.GetDlgCtrlID(hwnd) == EDIT_CTRL_ID or (legacy_combo and
                                                             _is_descendant(hwnd, legacy_combo))):
            edits.append(hwnd)
            return False
        return True

    user32.EnumChildWindows(dialog, _ENUM(cb), 0)
    return edits[0] if edits else None


def find_dialog_folder(dialog):
    """저장 창이 지금 열려 있는 폴더(주소 표시줄에서 읽음). 경로를 알 수 없으면 None."""
    found = []

    def cb(hwnd, _lparam):
        if _class_name(hwnd) == "ToolbarWindow32":
            path = parse_address_text(_window_text(hwnd))
            if path:
                found.append(path)
                return False
        return True

    user32.EnumChildWindows(dialog, _ENUM(cb), 0)
    return found[0] if found else None


def _is_descendant(hwnd, ancestor):
    while hwnd:
        if hwnd == ancestor:
            return True
        hwnd = user32.GetParent(hwnd)
    return False


def get_text(hwnd):
    length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, ctypes.cast(buf, ctypes.c_void_p).value)
    return buf.value


def set_text(hwnd, text):
    buf = ctypes.create_unicode_buffer(text)
    user32.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p).value)


class SaveDialogFixer:
    def __init__(self, downloads_dir, process_names=("chrome.exe",), interval=0.25,
                 is_paused=lambda: False, get_dir=None):
        self.downloads_dir = Path(downloads_dir)
        self.get_dir = get_dir or (lambda: self.downloads_dir)  # 감지 폴더가 바뀌어도 따라가도록
        self.process_names = tuple(n.lower() for n in process_names)
        self.interval = interval
        self.is_paused = is_paused
        self.changed = []          # (원래 이름, 바꾼 이름) 기록(확인·디버깅용)
        self._handled = set()
        self._tries = {}           # 창마다, 주소 표시줄이 채워지기를 기다린 횟수
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.poll_once()
            except Exception:  # 감시 스레드는 어떤 오류에도 죽지 않는다
                import traceback
                traceback.print_exc()

    def poll_once(self):
        dialogs = find_save_dialogs(self.process_names) if not self.is_paused() else []
        self._handled &= set(dialogs)   # 닫힌 창은 잊는다
        self._tries = {d: n for d, n in self._tries.items() if d in dialogs}
        for dlg in dialogs:
            if dlg in self._handled:
                continue
            edit = find_filename_edit(dlg)
            if not edit:
                continue
            current = get_text(edit)
            if not current:
                continue                # 아직 값이 채워지기 전: 다음 주기에 다시 본다
            folder = find_dialog_folder(dlg)
            if folder is None and self._tries.get(dlg, 0) < ADDRESS_WAIT_TRIES:
                self._tries[dlg] = self._tries.get(dlg, 0) + 1
                continue                # 주소 표시줄이 아직 채워지기 전일 수 있어 조금 더 기다린다
            self._handled.add(dlg)
            if folder is not None and folder.is_dir():
                new = suggest_name(current, folder)
            else:                       # 경로를 알 수 없는 특수 폴더: 감지 폴더 전체에서 같은 이름을 찾는다
                new = suggest_name(current, self.get_dir(), search_tree=True)
            if new:
                set_text(edit, new)
                self.changed.append((current, new))

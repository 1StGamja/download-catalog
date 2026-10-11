"""트레이 아이콘이 '숨겨진 아이콘' 칸에 가려지지 않고 작업표시줄에 바로 보이게 한다.

윈도우 11은 알림 영역 아이콘별 설정을 HKCU\\Control Panel\\NotifyIconSettings\\<번호> 에 저장하며,
IsPromoted=1 이면 항상 표시된다. 항목은 아이콘이 처음 등록될 때 만들어지므로 잠시 기다려 설정한다.
"""
import ctypes
import os
import threading
import time
import winreg

SETTINGS_KEY = r"Control Panel\NotifyIconSettings"


def current_exe():
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetModuleFileNameW(None, buf, 1024)
    return buf.value


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def promote(exe_path):
    """exe_path의 아이콘 항목에 IsPromoted=1을 설정한다. 설정한 항목 수를 돌려준다."""
    target, count = _norm(exe_path), 0
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
    except OSError:
        return 0
    with root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(root, name, 0,
                                    winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
                    exe, _ = winreg.QueryValueEx(key, "ExecutablePath")
                    if _norm(exe) != target:
                        continue
                    try:
                        promoted, _ = winreg.QueryValueEx(key, "IsPromoted")
                    except OSError:
                        promoted = None
                    if promoted != 1:
                        winreg.SetValueEx(key, "IsPromoted", 0, winreg.REG_DWORD, 1)
                    count += 1
            except OSError:
                continue
    return count


def promote_when_ready(timeout=20.0, interval=0.5, exe_path=None):
    """백그라운드로 항목이 생길 때까지 기다렸다가 설정한다(실패해도 프로그램에는 영향 없음)."""
    exe_path = exe_path or current_exe()

    def run():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if promote(exe_path):
                    return
            except Exception:
                return
            time.sleep(interval)

    threading.Thread(target=run, daemon=True).start()

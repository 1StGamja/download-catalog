"""Windows 시작 시 자동 실행 등록(HKCU\\...\\Run). 설치 프로그램이 쓰는 값과 같은 이름을 쓴다."""
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DownloadCatalog"


def command():
    """자동 실행 때 쓸 명령줄. 설치본(exe)이면 exe, 개발 중이면 pythonw + run.pyw."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    run_pyw = Path(__file__).resolve().parents[2] / "run.pyw"
    return f'"{pythonw}" "{run_pyw}"'


def is_enabled(name=VALUE_NAME):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, name)
            return True
    except OSError:
        return False


def set_enabled(enabled, name=VALUE_NAME):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass

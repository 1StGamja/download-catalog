"""중복 실행 방지 + 두 번째 실행이 첫 번째 프로그램에 "화면을 보여 달라"고 알리기.

뮤텍스 이름은 설치 프로그램(AppMutex)도 같은 이름으로 확인하므로 바꾸지 않는다.
"""
import ctypes
import os
import threading
from ctypes import wintypes

# 시험용: 환경변수를 지정하면 이름이 달라져 실제로 실행 중인 프로그램과 부딪히지 않는다.
_SUFFIX = os.environ.get("DOWNLOADCATALOG_INSTANCE_SUFFIX", "")
MUTEX_NAME = "DownloadCatalog_SingleInstance" + _SUFFIX
EVENT_NAME = "DownloadCatalog_ShowEvent" + _SUFFIX
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_k32.OpenEventW.restype = wintypes.HANDLE
_k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.SetEvent.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


class SingleInstance:
    def __init__(self, mutex_name=MUTEX_NAME, event_name=EVENT_NAME):
        self.event_name = event_name
        self._mutex = _k32.CreateMutexW(None, False, mutex_name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        self._event = None
        self._stop = threading.Event()

    def signal_existing(self):
        """이미 실행 중인 프로그램에 '화면 보여 줘' 신호를 보낸다. 보냈으면 True."""
        handle = _k32.OpenEventW(EVENT_MODIFY_STATE, False, self.event_name)
        if not handle:
            return False
        try:
            return bool(_k32.SetEvent(handle))
        finally:
            _k32.CloseHandle(handle)

    def listen(self, callback):
        """두 번째 실행의 신호를 기다리는 스레드를 시작한다(callback은 그 스레드에서 호출됨)."""
        self._event = _k32.CreateEventW(None, False, False, self.event_name)

        def run():
            while not self._stop.is_set():
                if _k32.WaitForSingleObject(self._event, 500) == WAIT_OBJECT_0:
                    try:
                        callback()
                    except Exception:
                        import traceback
                        traceback.print_exc()

        threading.Thread(target=run, daemon=True).start()

    def close(self):
        self._stop.set()
        if self._mutex:
            _k32.CloseHandle(self._mutex)
            self._mutex = None

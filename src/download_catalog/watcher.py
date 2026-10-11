"""Downloads 폴더 감시. 다운로드가 끝난(크기가 안정된) 파일만 콜백으로 알린다."""
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

IGNORED_SUFFIXES = (".crdownload", ".tmp", ".part", ".partial")


def is_ignored(path):
    name = Path(path).name.lower()
    return name.endswith(IGNORED_SUFFIXES) or name.startswith("~$") or name == "desktop.ini"


def in_hidden_dir(path, root):
    """root 아래 하위 폴더 중 이름이 '.'으로 시작하는 폴더(.git 등) 안의 파일이면 True."""
    try:
        parts = Path(path).relative_to(root).parts[:-1]
    except ValueError:
        return False
    return any(part.startswith(".") for part in parts)


def iter_files(folder, recursive=True):
    """folder 안의 파일들(recursive면 하위 폴더 포함, '.'으로 시작하는 폴더는 건너뜀)."""
    import os
    folder = Path(folder)
    if not recursive:
        try:
            for entry in os.scandir(folder):
                if entry.is_file():
                    yield Path(entry.path)
        except OSError:
            pass
        return
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            yield Path(dirpath) / name


def wait_until_stable(path, stable_for=2.0, timeout=600.0, poll=0.5):
    """파일 크기가 stable_for초 동안 변하지 않고 열 수 있으면 True."""
    path = Path(path)
    deadline = time.monotonic() + timeout
    last_size, since = -1, time.monotonic()
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False  # 사라진 파일(임시 파일 이름 변경 등)
        if size != last_size:
            last_size, since = size, time.monotonic()
        elif time.monotonic() - since >= stable_for:
            try:
                with open(path, "rb"):
                    return True
            except OSError:
                since = time.monotonic()
        time.sleep(poll)
    return False


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher):
        self.watcher = watcher

    def on_created(self, event):
        if event.is_directory:
            self.watcher.schedule_folder(event.src_path)
        else:
            self.watcher.schedule(event.src_path)

    def on_moved(self, event):  # .crdownload -> 최종 이름 / 폴더째 옮겨 온 경우
        if event.is_directory:
            self.watcher.schedule_folder(event.dest_path)
        else:
            self.watcher.schedule(event.dest_path)


class DownloadWatcher:
    def __init__(self, folder, callback, stable_for=2.0, recursive=True):
        self.folder = Path(folder)
        self.callback = callback
        self.stable_for = stable_for
        self.recursive = recursive
        self.paused = False
        self._inflight = set()
        self._lock = threading.Lock()
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.folder), recursive=recursive)

    def start(self):
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=5)

    def schedule_folder(self, folder):
        """폴더가 새로 생기거나 통째로 옮겨 왔을 때, 그 안의 파일들도 감지 대상으로 올린다.

        (폴더째 이름이 바뀌어 들어오면 안의 파일에 대한 개별 이벤트가 오지 않기 때문)
        """
        if self.paused or not self.recursive or Path(folder).name.startswith("."):
            return
        for path in iter_files(folder, recursive=True):
            self.schedule(path)

    def schedule(self, path):
        if self.paused or is_ignored(path) or in_hidden_dir(path, self.folder):
            return
        key = str(Path(path))
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
        threading.Thread(target=self._process, args=(key,), daemon=True).start()

    def _process(self, key):
        try:
            if wait_until_stable(key, stable_for=self.stable_for):
                self.callback(Path(key))
        except Exception:  # 감시 스레드는 어떤 오류에도 죽지 않는다
            import traceback
            traceback.print_exc()
        finally:
            with self._lock:
                self._inflight.discard(key)


class WatchController:
    """감시 폴더를 실행 중에 바꿀 수 있게 DownloadWatcher를 감싼다."""

    def __init__(self, folder, callback, stable_for=2.0, recursive=True):
        self.folder = Path(folder)
        self.callback = callback
        self.stable_for = stable_for
        self.recursive = recursive
        self._paused = False
        self._watcher = None

    @property
    def paused(self):
        return self._paused

    @paused.setter
    def paused(self, value):
        self._paused = bool(value)
        if self._watcher is not None:
            self._watcher.paused = self._paused

    def _new_watcher(self, folder):
        watcher = DownloadWatcher(folder, self.callback, self.stable_for, self.recursive)
        watcher.paused = self._paused
        watcher.start()
        return watcher

    def start(self):
        self._watcher = self._new_watcher(self.folder)

    def stop(self):
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

    def set_folder(self, folder):
        """새 폴더 감시를 먼저 시작한 뒤 이전 감시를 멈춘다(실패하면 기존 감시 유지)."""
        folder = Path(folder)
        if not folder.is_dir():
            raise NotADirectoryError(str(folder))
        if folder == self.folder:
            return
        new = self._new_watcher(folder)
        old, self._watcher, self.folder = self._watcher, new, folder
        if old is not None:
            old.stop()

    def set_recursive(self, recursive):
        """하위 폴더 감지를 켜거나 끈다(바뀐 경우에만 같은 폴더의 감시를 새로 시작)."""
        recursive = bool(recursive)
        if recursive == self.recursive:
            return
        previous, self.recursive = self.recursive, recursive
        try:
            new = self._new_watcher(self.folder)
        except Exception:
            self.recursive = previous   # 실패하면 기존 감시를 그대로 둔다
            raise
        old, self._watcher = self._watcher, new
        if old is not None:
            old.stop()

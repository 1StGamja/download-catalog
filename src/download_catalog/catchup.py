"""F1. 프로그램이 꺼져 있던 동안 폴더에 생긴 파일을 찾아서 기록한다."""
from datetime import datetime
from pathlib import Path

from .recorder import record_file
from .watcher import is_ignored, iter_files, wait_until_stable


def created_time(stat):
    """폴더에 생긴 시각(윈도우 생성 시각). 새 Python은 st_birthtime, 없으면 st_ctime."""
    return getattr(stat, "st_birthtime", stat.st_ctime)


def find_candidates(folder, since_ts, db, recursive=True, subfolder_since=None):
    """since_ts(epoch 초) 이후에 폴더(recursive면 하위 폴더 포함)에 생긴, 아직 기록에 없는 파일들(오래된 순).

    subfolder_since: 하위 폴더의 파일에만 적용하는 기준 시각(더 늦으면 그것을 따른다).
    하위 폴더 감지를 켜기 전에 생긴 파일을 거슬러 가져오지 않기 위해 쓴다.
    """
    folder = Path(folder)
    found = []
    for path in iter_files(folder, recursive):
        try:
            if is_ignored(path):
                continue
            created = created_time(path.stat())
        except OSError:
            continue
        limit = since_ts
        if subfolder_since is not None and path.parent != folder:
            limit = max(since_ts, subfolder_since)
        if created >= limit and not db.has_file_path(path):
            found.append((created, path))
    return [p for _c, p in sorted(found)]


def run(folder, since_ts, db, history_path=None, on_recorded=None, recursive=True, subfolder_since=None):
    """찾은 파일을 모두 기록하고 새로 만든 기록 id 목록을 돌려준다(팝업은 띄우지 않는다)."""
    ids = []
    for path in find_candidates(folder, since_ts, db, recursive, subfolder_since):
        try:
            if not wait_until_stable(path, stable_for=1.0, timeout=30):
                continue
            created = datetime.fromtimestamp(created_time(path.stat())).strftime("%Y-%m-%d %H:%M:%S")
            result = record_file(db, path, history_path, rename=False, downloaded_at=created)
        except OSError:
            continue
        if result is not None:
            ids.append(result[0])
            if on_recorded:
                on_recorded(result[0])
    return ids

"""완료된 파일 한 개를 조사해 DB에 기록한다(팝업보다 먼저 실행)."""
import time
from datetime import datetime
from pathlib import Path

from . import origin, versioning


def timestamped_path(path, now=None):
    """`file (1).zip` -> `file_2026-10-11-1530.zip` (같은 이름이 있으면 초, 번호를 덧붙임)."""
    path = Path(path)
    now = now or datetime.now()
    stem = versioning.strip_copy_suffix(path.stem)
    for stamp in (now.strftime("%Y-%m-%d-%H%M"), now.strftime("%Y-%m-%d-%H%M%S")):
        candidate = path.with_name(f"{stem}_{stamp}{path.suffix}")
        if not candidate.exists():
            return candidate
    n = 2
    while True:
        candidate = path.with_name(f"{stem}_{now.strftime('%Y-%m-%d-%H%M%S')}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def collided_with_existing(path):
    """Chrome이 이름 충돌 때문에 ` (N)`을 붙였고, 원래 이름의 파일이 실제로 있으면 True."""
    path = Path(path)
    stem = versioning.strip_copy_number(path.stem)
    if stem == path.stem:
        return False
    return path.with_name(stem + path.suffix).exists()


def rename_if_collided(path, tries=5, delay=1.0):
    """충돌했으면 `이름_년월일시분.확장자`로 바꾸고 새 경로를, 아니면(실패 포함) 원래 경로를 돌려준다."""
    path = Path(path)
    if not collided_with_existing(path):
        return path
    for attempt in range(tries):
        target = timestamped_path(path)
        try:
            path.rename(target)  # 대상이 이미 있으면 덮어쓰지 않고 실패한다(윈도우)
            return target
        except OSError:
            if attempt < tries - 1:
                time.sleep(delay)
    return path


def record_file(db, path, history_path=None, rename=True, downloaded_at=None):
    """기록 후 (record_id, Judgement)를 돌려준다. 이미 같은 경로·내용이 기록돼 있으면 None.

    rename=False: 이름 충돌 파일의 이름을 바꾸지 않는다(이미 폴더에 있던 파일을 가져올 때).
    downloaded_at: 받은 시각을 직접 지정(없으면 지금).
    """
    path = Path(path)
    sha = _hash_with_retry(path)
    if db.has_path(path, sha):
        return None
    judgement = versioning.judge(db, path.name, sha)
    info = origin.find_origin(path, history_path)  # Chrome History는 원래 이름으로 찾으므로 이름 변경 전에 조사
    if rename:
        path = rename_if_collided(path)
    record_id = db.add(
        file_name=path.name,
        base_name=versioning.base_name_of(path.name),
        file_path=str(path),
        size=path.stat().st_size,
        sha256=sha,
        downloaded_at=downloaded_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        source_url=info["source_url"],
        referrer_url=info["referrer_url"],
        version=judgement.version,
        prev_id=judgement.prev_id,
        duplicate_of=judgement.duplicate_of,
    )
    return record_id, judgement


def _hash_with_retry(path, tries=5, delay=1.0):
    for attempt in range(tries):
        try:
            return versioning.sha256_of(path)
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)

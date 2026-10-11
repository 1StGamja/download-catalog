"""파일 지문(SHA-256) 계산과 중복·새 버전 판단."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")


def sha256_of(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


# _년-월-일-시분[초][_번호] (이전 버전의 _년월일시분[초] 형식도 같은 계열로 인식)
_TIMESTAMP_SUFFIX = re.compile(r"_(?:\d{4}-\d{2}-\d{2}-\d{4}|\d{12})(?:\d{2})?(?:_\d+)?$")


def strip_copy_number(stem):
    """`setup (1)` -> `setup` (Chrome이 붙인 번호만 제거)."""
    return _COPY_SUFFIX.sub("", stem)


def strip_copy_suffix(stem):
    """`setup (1)`, `setup_2026-10-11-1530` -> `setup` (같은 계열 이름으로 환원)."""
    return _TIMESTAMP_SUFFIX.sub("", strip_copy_number(stem))


def base_name_of(file_name):
    """`setup (1).exe`, `setup_2026-10-11-1530.exe` -> `setup.exe` (소문자 통일)."""
    p = Path(file_name)
    return f"{strip_copy_suffix(p.stem)}{p.suffix}".lower()


@dataclass
class Judgement:
    kind: str          # "new" | "new_version" | "duplicate"
    version: int = 1
    prev_id: int = None
    duplicate_of: int = None
    related: object = None   # 비교 대상이 된 기존 기록(Row)


def judge(db, file_name, sha256):
    same = db.find_by_hash(sha256)
    if same is not None:
        return Judgement("duplicate", version=same["version"],
                         duplicate_of=same["id"], related=same)
    prev = db.latest_by_base_name(base_name_of(file_name))
    if prev is not None:
        return Judgement("new_version", version=prev["version"] + 1,
                         prev_id=prev["id"], related=prev)
    return Judgement("new")

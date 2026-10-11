"""파일의 출처(URL) 조사: Zone.Identifier 우선, 없으면 Chrome History DB."""
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

_CHROME_EPOCH_OFFSET = 11644473600  # 1601-01-01 ~ 1970-01-01 (초)


def parse_zone_identifier(text):
    """Zone.Identifier 본문에서 HostUrl, ReferrerUrl을 뽑는다."""
    result = {}
    text = text.replace("\x00", "")   # Chrome이 만든 Zone.Identifier 끝에는 널 문자가 붙어 있을 수 있다
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return {
        "source_url": result.get("HostUrl") or None,
        "referrer_url": result.get("ReferrerUrl") or None,
    }


def read_zone_identifier(path):
    try:
        with open(f"{path}:Zone.Identifier", "r", encoding="utf-8", errors="replace") as f:
            return parse_zone_identifier(f.read())
    except OSError:
        return {"source_url": None, "referrer_url": None}


def default_history_path():
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "Google" / "Chrome" / "User Data" / "Default" / "History"


def read_chrome_history(path, history_path=None):
    """Chrome History DB에서 해당 파일의 다운로드 정보를 찾는다(복사본으로 읽음)."""
    empty = {"source_url": None, "referrer_url": None}
    history_path = Path(history_path or default_history_path())
    if not history_path.exists():
        return empty
    tmpdir = tempfile.mkdtemp(prefix="dc_hist_")
    try:
        copy = Path(tmpdir) / "History"
        shutil.copy2(history_path, copy)
        with closing(sqlite3.connect(copy)) as conn:
            row = conn.execute(
                "SELECT id, tab_url, referrer FROM downloads "
                "WHERE lower(target_path) = lower(?) ORDER BY end_time DESC LIMIT 1",
                (str(path),),
            ).fetchone()
            if row is None:
                return empty
            dl_id, tab_url, referrer = row
            chain = conn.execute(
                "SELECT url FROM downloads_url_chains WHERE id = ? "
                "ORDER BY chain_index DESC LIMIT 1", (dl_id,)
            ).fetchone()
            return {
                "source_url": (chain[0] if chain else None),
                "referrer_url": tab_url or referrer or None,
            }
    except (OSError, sqlite3.Error):
        return empty
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def find_origin(path, history_path=None):
    """출처 정보를 dict로. 아무 정보도 없으면 값은 None."""
    info = read_zone_identifier(path)
    if info["source_url"] and info["referrer_url"]:
        return info
    hist = read_chrome_history(path, history_path)
    return {
        "source_url": info["source_url"] or hist["source_url"],
        "referrer_url": info["referrer_url"] or hist["referrer_url"],
    }

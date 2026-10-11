"""SQLite 기록 저장소. 호출마다 연결을 열고 닫아 스레드 간 충돌을 피한다."""
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from .urlutil import domain_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name     TEXT NOT NULL,
    base_name     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    size          INTEGER,
    sha256        TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    source_url    TEXT,
    referrer_url  TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    prev_id       INTEGER,
    duplicate_of  INTEGER,
    purpose       TEXT DEFAULT '',
    memo          TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sha ON downloads(sha256);
CREATE INDEX IF NOT EXISTS idx_base ON downloads(base_name);
"""

SCHEMA_VERSION = 1   # PRAGMA user_version. 1: domain, auto_skipped 열 추가

COLUMNS = (
    "file_name", "base_name", "file_path", "size", "sha256", "downloaded_at",
    "source_url", "referrer_url", "version", "prev_id", "duplicate_of",
    "purpose", "memo", "domain", "auto_skipped",
)


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._backup_before_migration()
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- 저장 구조 버전 관리 ----
    def _backup_before_migration(self):
        """기존 DB의 구조를 바꾸기 전에 파일을 통째로 백업해 둔다."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'downloads'").fetchone()
        if has_table and version < SCHEMA_VERSION:
            shutil.copy2(self.path, self.path.with_name(f"{self.path.name}.bak-v{version}"))

    @staticmethod
    def _migrate(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(downloads)")}
            if "domain" not in existing:
                conn.execute("ALTER TABLE downloads ADD COLUMN domain TEXT")
            if "auto_skipped" not in existing:
                conn.execute("ALTER TABLE downloads ADD COLUMN auto_skipped INTEGER NOT NULL DEFAULT 0")
            for row in conn.execute("SELECT id, source_url, referrer_url FROM downloads").fetchall():
                domain = domain_of(row["source_url"]) or domain_of(row["referrer_url"])
                conn.execute("UPDATE downloads SET domain = ? WHERE id = ?", (domain, row["id"]))
            conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON downloads(domain)")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    # ---- 기본 입출력 ----
    def add(self, **fields):
        """기록 한 건을 저장하고 id를 돌려준다."""
        record = {c: fields.get(c) for c in COLUMNS}
        record["version"] = record["version"] or 1
        record["purpose"] = record["purpose"] or ""
        record["memo"] = record["memo"] or ""
        record["auto_skipped"] = record["auto_skipped"] or 0
        if record["domain"] is None:
            record["domain"] = domain_of(record["source_url"]) or domain_of(record["referrer_url"])
        placeholders = ", ".join("?" for _ in COLUMNS)
        sql = f"INSERT INTO downloads ({', '.join(COLUMNS)}) VALUES ({placeholders})"
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute(sql, [record[c] for c in COLUMNS])
            return cur.lastrowid

    def get(self, record_id):
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM downloads WHERE id = ?", (record_id,)
            ).fetchone()

    def find_by_hash(self, sha256):
        """같은 내용의 가장 오래된 기록(원본)."""
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM downloads WHERE sha256 = ? AND duplicate_of IS NULL "
                "ORDER BY id LIMIT 1", (sha256,)
            ).fetchone()

    def latest_by_base_name(self, base_name):
        """같은 계열 이름의 가장 최신 버전 기록."""
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM downloads WHERE base_name = ? AND duplicate_of IS NULL "
                "ORDER BY version DESC, id DESC LIMIT 1", (base_name,)
            ).fetchone()

    def has_path(self, file_path, sha256):
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM downloads WHERE file_path = ? AND sha256 = ? LIMIT 1",
                (str(file_path), sha256),
            ).fetchone()
            return row is not None

    def has_file_path(self, file_path):
        """이 경로의 파일이 이미 기록돼 있는지(내용과 무관)."""
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT 1 FROM downloads WHERE lower(file_path) = lower(?) LIMIT 1",
                (str(file_path),)).fetchone() is not None

    def update_note(self, record_id, purpose, memo):
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    "UPDATE downloads SET purpose = ?, memo = ? WHERE id = ?",
                    (purpose, memo, record_id),
                )

    def update_purpose_many(self, record_ids, purpose, memo=None):
        """여러 기록의 목적(과 memo가 None이 아니면 메모)을 한 번에 바꾼다."""
        record_ids = list(record_ids)
        if not record_ids:
            return 0
        marks = ", ".join("?" for _ in record_ids)
        with closing(self._connect()) as conn:
            with conn:
                if memo is None:
                    cur = conn.execute(
                        f"UPDATE downloads SET purpose = ? WHERE id IN ({marks})",
                        [purpose, *record_ids])
                else:
                    cur = conn.execute(
                        f"UPDATE downloads SET purpose = ?, memo = ? WHERE id IN ({marks})",
                        [purpose, memo, *record_ids])
            return cur.rowcount

    def set_auto_skipped(self, record_id, flag=True):
        """제외 규칙에 걸려 팝업 없이 기록만 한 파일 표시(미입력 목록에서 빠진다)."""
        with closing(self._connect()) as conn:
            with conn:
                conn.execute("UPDATE downloads SET auto_skipped = ? WHERE id = ?",
                             (1 if flag else 0, record_id))

    def delete(self, record_id):
        with closing(self._connect()) as conn:
            with conn:
                conn.execute("DELETE FROM downloads WHERE id = ?", (record_id,))

    def delete_many(self, record_ids):
        """여러 기록을 한 번에(하나의 트랜잭션으로) 삭제하고 지운 개수를 돌려준다."""
        record_ids = list(record_ids)
        if not record_ids:
            return 0
        placeholders = ", ".join("?" for _ in record_ids)
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute(
                    f"DELETE FROM downloads WHERE id IN ({placeholders})", record_ids)
            return cur.rowcount

    # ---- 검색·필터 ----
    def search(self, text="", *, days=None, purpose=None, unfilled=False,
               new_version=False, hide_duplicates=False):
        """이름·URL·태그·메모에서 검색하고 조건으로 거른다(최신순).

        days: 최근 N일(0이면 오늘만). purpose: 목적이 정확히 같은 것.
        unfilled: 목적을 안 쓴 것(규칙으로 제외된 것은 뺀다). new_version: v2 이상.
        """
        where, params = [], []
        text = (text or "").strip()
        if text:
            like = f"%{text}%"
            where.append("(file_name LIKE ? OR source_url LIKE ? OR referrer_url LIKE ? "
                         "OR purpose LIKE ? OR memo LIKE ? OR domain LIKE ?)")
            params += [like] * 6
        if days is not None:
            start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            start -= timedelta(days=days)
            where.append("downloaded_at >= ?")
            params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
        if purpose:
            where.append("purpose = ?")
            params.append(purpose)
        if unfilled:
            where.append("purpose = '' AND auto_skipped = 0")
        if new_version:
            where.append("version >= 2 AND duplicate_of IS NULL")
        if hide_duplicates:
            where.append("duplicate_of IS NULL")
        sql = "SELECT * FROM downloads"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC"
        with closing(self._connect()) as conn:
            return conn.execute(sql, params).fetchall()

    def count_all(self):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]

    def count_unfilled(self):
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE purpose = '' AND auto_skipped = 0"
            ).fetchone()[0]

    def count_today(self):
        today = datetime.now().strftime("%Y-%m-%d 00:00:00")
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM downloads WHERE downloaded_at >= ?",
                                (today,)).fetchone()[0]

    def unfilled_rows(self):
        return self.search(unfilled=True)

    def recent(self, limit=5):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT * FROM downloads ORDER BY id DESC LIMIT ?",
                                (limit,)).fetchall()

    def latest_downloaded_at(self):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT MAX(downloaded_at) FROM downloads").fetchone()[0]

    def distinct_purposes(self):
        with closing(self._connect()) as conn:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT purpose FROM downloads WHERE purpose != '' ORDER BY purpose")]

    # ---- 입력 제안(F2) ----
    def last_note_for_domain(self, domain):
        """같은 사이트에서 마지막으로 입력한 (목적, 메모). 없으면 None."""
        if not domain:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT purpose, memo FROM downloads WHERE domain = ? AND purpose != '' "
                "ORDER BY id DESC LIMIT 1", (domain,)).fetchone()
            return (row["purpose"], row["memo"] or "") if row else None

    def last_purpose(self):
        """가장 최근에 입력한 목적(사이트 무관). 없으면 None."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT purpose FROM downloads WHERE purpose != '' "
                               "ORDER BY id DESC LIMIT 1").fetchone()
            return row["purpose"] if row else None

    # ---- 백업 ----
    def backup_to(self, dest):
        """실행 중에도 안전하게 DB를 다른 파일로 복사한다."""
        with closing(self._connect()) as src, closing(sqlite3.connect(dest)) as dst:
            src.backup(dst)

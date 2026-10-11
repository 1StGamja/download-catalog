import sqlite3
import threading
import time
from contextlib import closing

import pytest

from download_catalog import origin, versioning
from download_catalog.db import Database
from download_catalog.recorder import record_file
from download_catalog.watcher import DownloadWatcher, is_ignored


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "data" / "catalog.db")


def write_with_zone(path, content, host=None, referrer=None):
    path.write_bytes(content)
    if host or referrer:
        with open(f"{path}:Zone.Identifier", "w", encoding="utf-8") as f:
            f.write("[ZoneTransfer]\nZoneId=3\n")
            if referrer:
                f.write(f"ReferrerUrl={referrer}\n")
            if host:
                f.write(f"HostUrl={host}\n")


# ---- db ----
def test_db_add_get_search_update(db):
    rid = db.add(file_name="a.exe", base_name="a.exe", file_path="C:/d/a.exe",
                 sha256="x", downloaded_at="2026-10-11 10:00:00",
                 source_url="https://site.com/a.exe")
    assert db.get(rid)["file_name"] == "a.exe"
    db.update_note(rid, "업무", "설치용")
    assert [r["id"] for r in db.search("설치")] == [rid]
    assert [r["id"] for r in db.search("site.com")] == [rid]
    assert db.search("없는검색어") == []
    db.delete(rid)
    assert db.get(rid) is None


# ---- versioning ----
def test_base_name_strips_chrome_number():
    assert versioning.base_name_of("Setup (1).EXE") == "setup.exe"
    assert versioning.base_name_of("report (12).pdf") == "report.pdf"
    assert versioning.base_name_of("v2 (final).pdf") == "v2 (final).pdf"


def test_sha256_known_value(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"abc")
    assert versioning.sha256_of(f) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_judge_new_version_duplicate(db):
    def add(name, sha, version=1, dup=None, prev=None):
        return db.add(file_name=name, base_name=versioning.base_name_of(name),
                      file_path=name, sha256=sha, downloaded_at="t",
                      version=version, duplicate_of=dup, prev_id=prev)

    assert versioning.judge(db, "setup.exe", "h1").kind == "new"
    first = add("setup.exe", "h1")
    j = versioning.judge(db, "setup (1).exe", "h2")
    assert (j.kind, j.version, j.prev_id) == ("new_version", 2, first)
    second = add("setup (1).exe", "h2", version=2, prev=first)
    j = versioning.judge(db, "setup (2).exe", "h3")
    assert (j.kind, j.version, j.prev_id) == ("new_version", 3, second)
    j = versioning.judge(db, "copy.exe", "h1")
    assert (j.kind, j.duplicate_of) == ("duplicate", first)


# ---- origin ----
def test_parse_zone_identifier():
    text = "[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=https://a.com/page\r\nHostUrl=https://a.com/f.zip\r\n"
    assert origin.parse_zone_identifier(text) == {
        "source_url": "https://a.com/f.zip", "referrer_url": "https://a.com/page"}


def test_parse_zone_identifier_strips_nul():
    # Chrome이 만든 Zone.Identifier는 값 끝에 널 문자가 붙어 있을 수 있다
    text = "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://a.com/f.zip\x00\r\nReferrerUrl=https://a.com/p\x00\x00"
    assert origin.parse_zone_identifier(text) == {"source_url": "https://a.com/f.zip", "referrer_url": "https://a.com/p"}


def test_read_real_zone_identifier(tmp_path):
    f = tmp_path / "f.zip"
    write_with_zone(f, b"data", "https://a.com/f.zip", "https://a.com/page")
    info = origin.read_zone_identifier(f)
    assert info["source_url"] == "https://a.com/f.zip"
    assert info["referrer_url"] == "https://a.com/page"


def test_zone_missing_returns_none(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_bytes(b"x")
    assert origin.read_zone_identifier(f) == {"source_url": None, "referrer_url": None}


def make_fake_history(path, target, url, tab_url):
    with closing(sqlite3.connect(path)) as c:
        c.execute("CREATE TABLE downloads (id INTEGER, target_path TEXT, tab_url TEXT, "
                  "referrer TEXT, end_time INTEGER)")
        c.execute("CREATE TABLE downloads_url_chains (id INTEGER, chain_index INTEGER, url TEXT)")
        c.execute("INSERT INTO downloads VALUES (1, ?, ?, '', 100)", (str(target), tab_url))
        c.execute("INSERT INTO downloads_url_chains VALUES (1, 0, 'https://redirect/x')")
        c.execute("INSERT INTO downloads_url_chains VALUES (1, 1, ?)", (url,))
        c.commit()


def test_chrome_history_fallback(tmp_path):
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"x")
    hist = tmp_path / "History"
    make_fake_history(hist, target, "https://real.com/doc.pdf", "https://real.com/list")
    info = origin.find_origin(target, history_path=hist)
    assert info == {"source_url": "https://real.com/doc.pdf",
                    "referrer_url": "https://real.com/list"}


def test_origin_unknown(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"x")
    info = origin.find_origin(f, history_path=tmp_path / "nope")
    assert info == {"source_url": None, "referrer_url": None}


# ---- recorder (전체 흐름) ----
def test_record_flow_new_version_duplicate(db, tmp_path):
    dl = tmp_path / "dl"
    dl.mkdir()
    a = dl / "setup.exe"
    write_with_zone(a, b"v1", "https://x.com/setup.exe", "https://x.com/dl")
    rid1, j1 = record_file(db, a, history_path=tmp_path / "none")
    assert j1.kind == "new" and db.get(rid1)["source_url"] == "https://x.com/setup.exe"

    b = dl / "setup (1).exe"
    write_with_zone(b, b"v2-changed")
    rid2, j2 = record_file(db, b, history_path=tmp_path / "none")
    assert j2.kind == "new_version" and db.get(rid2)["version"] == 2
    assert db.get(rid2)["prev_id"] == rid1

    c = dl / "setup (2).exe"
    c.write_bytes(b"v1")
    rid3, j3 = record_file(db, c, history_path=tmp_path / "none")
    assert j3.kind == "duplicate" and db.get(rid3)["duplicate_of"] == rid1

    assert record_file(db, a, history_path=tmp_path / "none") is None  # 같은 경로 재기록 방지


# ---- watcher ----
def test_ignored_names():
    assert is_ignored("C:/d/file.crdownload")
    assert is_ignored("C:/d/x.tmp")
    assert not is_ignored("C:/d/file.pdf")


def test_watcher_detects_finished_file_and_ignores_partial(tmp_path):
    found, ev = [], threading.Event()

    def cb(p):
        found.append(p.name)
        ev.set()

    w = DownloadWatcher(tmp_path, cb, stable_for=0.5)
    w.start()
    try:
        # Chrome 방식: 임시 파일에 쓰다가 최종 이름으로 변경
        part = tmp_path / "big.zip.crdownload"
        part.write_bytes(b"1")
        time.sleep(0.3)
        part.write_bytes(b"12345")
        part.rename(tmp_path / "big.zip")
        assert ev.wait(10), "다운로드 완료 감지 실패"
        time.sleep(1)
        assert found == ["big.zip"]
    finally:
        w.stop()


def test_watcher_paused_ignores(tmp_path):
    found = []
    w = DownloadWatcher(tmp_path, lambda p: found.append(p), stable_for=0.3)
    w.paused = True
    w.start()
    try:
        (tmp_path / "a.txt").write_bytes(b"x")
        time.sleep(1.5)
        assert found == []
    finally:
        w.stop()


# ---- 이름 충돌 시 타임스탬프 이름으로 변경 ----
from datetime import datetime
from download_catalog.recorder import rename_if_collided, timestamped_path


def test_base_name_strips_timestamp():
    assert versioning.base_name_of("setup_2026-10-11-1530.exe") == "setup.exe"
    assert versioning.base_name_of("setup_2026-10-11-153045.exe") == "setup.exe"
    assert versioning.base_name_of("setup_2026-10-11-153045_2.exe") == "setup.exe"
    assert versioning.base_name_of("setup_2026-10-11-1530 (1).exe") == "setup.exe"
    assert versioning.base_name_of("setup_202610111530.exe") == "setup.exe"     # 이전 형식도 인식
    assert versioning.base_name_of("data_2024.csv") == "data_2024.csv"  # 12자리 숫자가 아니면 유지


def test_timestamped_path_format(tmp_path):
    p = tmp_path / "SG-PDF (1).zip"
    assert timestamped_path(p, datetime(2026, 10, 11, 15, 30, 45)).name == "SG-PDF_2026-10-11-1530.zip"


def test_timestamped_path_avoids_existing(tmp_path):
    (tmp_path / "a_2026-10-11-1530.zip").write_bytes(b"x")
    p = tmp_path / "a (1).zip"
    assert timestamped_path(p, datetime(2026, 10, 11, 15, 30, 45)).name == "a_2026-10-11-153045.zip"


def test_rename_when_original_exists(tmp_path):
    (tmp_path / "a.zip").write_bytes(b"old")
    new = tmp_path / "a (1).zip"
    new.write_bytes(b"new")
    result = rename_if_collided(new)
    assert result != new and not new.exists() and result.exists()
    assert result.name.startswith("a_") and result.suffix == ".zip"
    assert (tmp_path / "a.zip").read_bytes() == b"old"


def test_no_rename_without_collision(tmp_path):
    only = tmp_path / "report (1).pdf"          # 원래 이름 파일이 없으면 사용자가 붙인 이름으로 보고 유지
    only.write_bytes(b"x")
    assert rename_if_collided(only) == only and only.exists()
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(b"x")
    assert rename_if_collided(plain) == plain


def test_record_renames_and_keeps_origin_and_version(db, tmp_path):
    (tmp_path / "pkg.zip").write_bytes(b"v1")
    dup = tmp_path / "pkg (1).zip"
    write_with_zone(dup, b"v2-new", "https://x.com/pkg.zip", "https://x.com/page")
    rid, j = record_file(db, dup, history_path=tmp_path / "none")
    row = db.get(rid)
    assert not dup.exists()
    assert row["file_name"].startswith("pkg_") and (tmp_path / row["file_name"]).exists()
    assert row["file_path"] == str(tmp_path / row["file_name"])
    assert row["source_url"] == "https://x.com/pkg.zip"   # 이름 변경 후에도 출처 유지(ADS가 함께 이동)
    assert record_file(db, tmp_path / row["file_name"], history_path=tmp_path / "none") is None


# ---- 저장 창 파일명 자동 변경 ----
from download_catalog.savedialog import suggest_name


def test_suggest_name_changes_only_on_collision(tmp_path):
    (tmp_path / "a.zip").write_bytes(b"x")
    now = datetime(2026, 10, 11, 15, 30)
    assert suggest_name("a (1).zip", tmp_path, now) == "a_2026-10-11-1530.zip"
    assert suggest_name("b (1).zip", tmp_path, now) is None      # 원래 이름 파일이 없음
    assert suggest_name("a.zip", tmp_path, now) is None          # 충돌 이름이 아님
    assert suggest_name("", tmp_path, now) is None
    assert suggest_name(r"C:\x\a (1).zip", tmp_path, now) is None  # 경로가 섞인 값은 건드리지 않음


def test_delete_many(db):
    ids = [db.add(file_name=f"f{i}", base_name=f"f{i}", file_path=f"p{i}", sha256=str(i),
                  downloaded_at="t") for i in range(4)]
    assert db.delete_many(ids[:3]) == 3
    assert [r["id"] for r in db.search("")] == [ids[3]]
    assert db.delete_many([]) == 0


# ---- 환경설정: 감지 폴더 변경 ----
from download_catalog.settings import Settings, default_watch_dir
from download_catalog.watcher import WatchController


def test_settings_roundtrip_and_defaults(tmp_path):
    path = tmp_path / "data" / "settings.json"
    s = Settings(path)
    assert s.watch_dir == default_watch_dir()           # 파일이 없으면 기본 다운로드 폴더
    s.watch_dir = tmp_path / "한글 폴더"
    s.save()
    assert Settings(path).watch_dir == tmp_path / "한글 폴더"


def test_settings_corrupt_file_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    assert Settings(path).watch_dir == default_watch_dir()
    path.write_text("[1, 2]", encoding="utf-8")
    assert Settings(path).watch_dir == default_watch_dir()


def test_watch_controller_switches_folder_live(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    found = []
    c = WatchController(a, lambda p: found.append(p.parent.name + "/" + p.name), stable_for=0.4)
    c.start()
    try:
        (a / "one.txt").write_bytes(b"1")
        time.sleep(2.5)
        c.set_folder(b)
        (a / "ignored.txt").write_bytes(b"x")    # 이전 폴더: 이제 감지되면 안 됨
        (b / "two.txt").write_bytes(b"2")
        time.sleep(2.5)
        assert sorted(found) == ["a/one.txt", "b/two.txt"]
        assert c.folder == b
    finally:
        c.stop()


def test_watch_controller_bad_folder_keeps_old_and_pause_survives(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    found = []
    c = WatchController(a, lambda p: found.append(p.name), stable_for=0.3)
    c.start()
    try:
        with pytest.raises(NotADirectoryError):
            c.set_folder(tmp_path / "missing")
        assert c.folder == a
        c.paused = True
        c.set_folder(b)                           # 일시정지 상태는 새 감시에도 유지
        (b / "p.txt").write_bytes(b"x")
        time.sleep(1.5)
        assert found == []
        c.paused = False
        (b / "q.txt").write_bytes(b"x")
        time.sleep(2)
        assert found == ["q.txt"]
    finally:
        c.stop()

"""개선 1차: DB 마이그레이션·필터, 설정, 제외 규칙, 따라잡기, 자동 실행, 단일 실행."""
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta

import pytest

from download_catalog import autostart, catchup, rules
from download_catalog.db import SCHEMA_VERSION, Database
from download_catalog.settings import DEFAULT_PURPOSES, Settings, normalize_domain, normalize_ext
from download_catalog.single_instance import SingleInstance
from download_catalog.urlutil import domain_of, human_size


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "data" / "catalog.db")


def add(db, name="a.zip", url=None, purpose="", when=None, **kw):
    return db.add(file_name=name, base_name=name, file_path=f"C:/d/{name}", sha256=name,
                  downloaded_at=when or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  source_url=url, purpose=purpose, **kw)


# ---- urlutil ----
def test_domain_and_size_helpers():
    assert domain_of("https://www.GitHub.com/a/b?x=1") == "github.com"
    assert domain_of("https://drive.usercontent.google.com/download?id=1") == "drive.usercontent.google.com"
    assert domain_of("") is None and domain_of(None) is None and domain_of("not a url") is None
    assert human_size(0) == "0 B" and human_size(1536) == "1.5 KB" and human_size(52961000) == "50.5 MB"
    assert human_size(None) == ""


# ---- DB: 마이그레이션 ----
def test_new_db_has_version_and_columns(db):
    with closing(db._connect()) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        cols = {r[1] for r in c.execute("PRAGMA table_info(downloads)")}
    assert {"domain", "auto_skipped"} <= cols


def test_migrates_old_db_keeps_rows_and_backs_up(tmp_path):
    path = tmp_path / "old" / "catalog.db"
    path.parent.mkdir()
    with closing(sqlite3.connect(path)) as c:      # 1.0.0 시절의 구조(버전 0, 새 열 없음)
        c.executescript("""
            CREATE TABLE downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL,
              base_name TEXT NOT NULL, file_path TEXT NOT NULL, size INTEGER, sha256 TEXT NOT NULL,
              downloaded_at TEXT NOT NULL, source_url TEXT, referrer_url TEXT,
              version INTEGER NOT NULL DEFAULT 1, prev_id INTEGER, duplicate_of INTEGER,
              purpose TEXT DEFAULT '', memo TEXT DEFAULT '');
            INSERT INTO downloads (file_name, base_name, file_path, sha256, downloaded_at, source_url, purpose)
              VALUES ('x.zip','x.zip','C:/x.zip','h','2026-10-01 10:00:00','https://www.site.com/x.zip','학습');
        """)
        c.commit()
    db = Database(path)
    row = db.search("")[0]
    assert (row["file_name"], row["purpose"], row["domain"], row["auto_skipped"]) == ("x.zip", "학습", "site.com", 0)
    assert (tmp_path / "old" / "catalog.db.bak-v0").exists()
    Database(path)                                   # 두 번째 열기: 다시 옮기거나 백업하지 않음
    assert len(list((tmp_path / "old").glob("*.bak-*"))) == 1


# ---- DB: 필터·집계 ----
def test_search_filters(db):
    now = datetime.now()
    old = (now - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
    a = add(db, "today.zip", "https://github.com/x", "개발")
    b = add(db, "old.zip", "https://site.com/y", "", when=old)
    c = add(db, "v2.zip", "https://github.com/z", "개발", version=2)
    d = add(db, "dup.zip", duplicate_of=a)
    e = add(db, "skipped.png", auto_skipped=1)

    def ids(rows):
        return sorted(r["id"] for r in rows)

    assert ids(db.search("")) == sorted([a, b, c, d, e])
    assert ids(db.search("github")) == sorted([a, c])               # 도메인/URL 검색
    assert ids(db.search(days=0)) == sorted([a, c, d, e])           # 오늘
    assert ids(db.search(days=30)) == sorted([a, b, c, d, e])
    assert ids(db.search(purpose="개발")) == sorted([a, c])
    assert ids(db.search(unfilled=True)) == sorted([b, d])          # 제외 규칙으로 건너뛴 e는 빠짐
    assert ids(db.search(new_version=True)) == [c]
    assert ids(db.search(hide_duplicates=True)) == sorted([a, b, c, e])
    assert ids(db.search("github", days=0, hide_duplicates=True)) == sorted([a, c])
    assert (db.count_all(), db.count_unfilled(), db.count_today()) == (5, 2, 4)
    assert [r["id"] for r in db.recent(2)] == [e, d]
    assert db.distinct_purposes() == ["개발"]


def test_suggestions_by_domain_and_last(db):
    assert db.last_note_for_domain("github.com") is None and db.last_purpose() is None
    add(db, "1.zip", "https://github.com/a", "개발")
    b = add(db, "2.zip", "https://github.com/b", "학습")
    add(db, "3.zip", "https://other.com/c", "개인")
    db.update_note(b, "학습", "강의 자료")
    assert db.last_note_for_domain("github.com") == ("학습", "강의 자료")   # 가장 최근 입력
    assert db.last_purpose() == "개인"
    add(db, "4.zip", "https://github.com/c", "")                         # 목적 비었으면 제안에서 제외
    assert db.last_note_for_domain("github.com") == ("학습", "강의 자료")


def test_bulk_update_and_auto_skip(db):
    ids = [add(db, f"{i}.zip") for i in range(3)]
    assert db.update_purpose_many(ids[:2], "업무") == 2
    assert [db.get(i)["purpose"] for i in ids] == ["업무", "업무", ""]
    db.update_note(ids[0], "업무", "메모")
    db.update_purpose_many([ids[0]], "학습", memo="")
    assert (db.get(ids[0])["purpose"], db.get(ids[0])["memo"]) == ("학습", "")
    db.set_auto_skipped(ids[2])
    assert db.count_unfilled() == 0
    assert db.has_file_path("c:/D/0.ZIP") and not db.has_file_path("C:/d/none.zip")


def test_backup_to(db, tmp_path):
    add(db, "x.zip")
    dest = tmp_path / "backup.db"
    db.backup_to(dest)
    assert Database(dest).count_all() == 1


# ---- 설정 ----
def test_settings_defaults_and_validation(tmp_path):
    s = Settings(tmp_path / "s.json")
    assert (s.get("popup_mode"), s.get("autoskip_seconds"), s.get("min_size_mb")) == ("popup", 0, 0.0)
    assert s.purposes == DEFAULT_PURPOSES
    s.purposes.append("변경해도 기본값 안 바뀜")
    assert s.purposes == DEFAULT_PURPOSES
    s.set("popup_mode", "엉뚱한값")
    s.set("purposes", [])
    s.set("min_size_mb", "abc")
    assert (s.get("popup_mode"), s.purposes, s.get("min_size_mb")) == ("popup", DEFAULT_PURPOSES, 0.0)
    s.set("min_size_mb", 2)
    s.set("exclude_exts", ["png"])
    s.set("catalog", {"geometry": "900x500"})
    s.save()
    t = Settings(tmp_path / "s.json")
    assert t.get("min_size_mb") == 2 and t.get("exclude_exts") == ["png"]
    assert t.get("catalog")["geometry"] == "900x500" and t.get("catalog")["sort"] == ["downloaded_at", True]
    with pytest.raises(KeyError):
        s.set("없는키", 1)


def test_normalize_helpers():
    assert normalize_ext(" .PNG ") == "png" and normalize_ext("*.jpg") == "jpg"
    assert normalize_domain("https://www.GitHub.com/x/y") == "github.com"


# ---- 제외 규칙 ----
def test_prompt_rules(tmp_path):
    s = Settings(tmp_path / "s.json")
    assert rules.prompt_excluded(s, "a.png", 10, "x.com") is None          # 아무 규칙 없음
    s.set("min_size_mb", 1)
    s.set("exclude_exts", ["png"])
    s.set("exclude_domains", ["github.com"])
    assert rules.prompt_excluded(s, "a.zip", 500_000, "x.com")             # 1MB 미만
    assert rules.prompt_excluded(s, "a.zip", 5_000_000, "x.com") is None
    assert rules.prompt_excluded(s, "photo.PNG", 5_000_000, "x.com")       # 확장자(대소문자 무관)
    assert rules.prompt_excluded(s, "a.zip", 5_000_000, "github.com")
    assert rules.prompt_excluded(s, "a.zip", 5_000_000, "gist.github.com")  # 하위 도메인 포함
    assert rules.prompt_excluded(s, "a.zip", 5_000_000, "notgithub.com") is None


# ---- F1: 놓친 파일 따라잡기 ----
def test_catchup_finds_only_new_unrecorded_files(db, tmp_path):
    folder = tmp_path / "dl"
    folder.mkdir()
    (folder / "old.zip").write_bytes(b"old")
    time.sleep(1.2)
    since = time.time()
    time.sleep(0.2)
    (folder / "new1.zip").write_bytes(b"1")
    (folder / "new2.zip").write_bytes(b"22")
    (folder / "partial.zip.crdownload").write_bytes(b"x")
    (folder / "sub").mkdir()

    def names():
        return [p.name for p in catchup.find_candidates(folder, since, db)]

    assert names() == ["new1.zip", "new2.zip"]
    ids = catchup.run(folder, since, db)
    assert len(ids) == 2 and db.count_unfilled() == 2          # 팝업 없이 기록만, 미입력 상태
    assert names() == []                                        # 다시 돌려도 중복 기록 없음
    assert catchup.run(folder, since, db) == []
    assert catchup.find_candidates(tmp_path / "없는폴더", since, db) == []


def test_catchup_does_not_rename_colliding_names(db, tmp_path):
    folder = tmp_path / "dl"
    folder.mkdir()
    since = time.time() - 5
    (folder / "a.zip").write_bytes(b"1")
    (folder / "a (1).zip").write_bytes(b"2")
    catchup.run(folder, since, db)
    assert sorted(p.name for p in folder.iterdir()) == ["a (1).zip", "a.zip"]


# ---- 자동 실행 등록 ----
def test_autostart_toggle_uses_given_name():
    name = "DownloadCatalogUnitTest"
    try:
        assert not autostart.is_enabled(name)
        autostart.set_enabled(True, name)
        assert autostart.is_enabled(name)
        autostart.set_enabled(False, name)
        assert not autostart.is_enabled(name)
        autostart.set_enabled(False, name)       # 이미 없어도 오류 없음
    finally:
        autostart.set_enabled(False, name)


def test_autostart_command_is_quoted_path():
    cmd = autostart.command()
    assert cmd.startswith('"') and ("run.pyw" in cmd or cmd.endswith('.exe"'))


# ---- U7: 두 번째 실행이 첫 번째에 신호 ----
def test_second_instance_signals_first():
    first = SingleInstance("DC_TestMutex_1", "DC_TestEvent_1")
    assert not first.already_running
    got = []
    first.listen(lambda: got.append(1))
    second = SingleInstance("DC_TestMutex_1", "DC_TestEvent_1")
    assert second.already_running and second.signal_existing()
    for _ in range(20):
        if got:
            break
        time.sleep(0.1)
    first.close()
    second.close()
    assert got == [1]


def test_signal_without_running_instance_returns_false():
    assert SingleInstance("DC_TestMutex_2", "DC_NoSuchEvent").signal_existing() is False


# ---- 저장 창: 창이 열린 폴더 기준으로 충돌 판단 ----
from pathlib import Path as _P
from download_catalog.savedialog import exists_in_tree, parse_address_text, suggest_name


def test_parse_address_text():
    assert parse_address_text(r"주소: C:\Users\user\Downloads\Claude_Output") == _P("C:/Users/user/Downloads/Claude_Output")
    assert parse_address_text("Address: D:/work/a b") == _P("D:/work/a b")
    assert parse_address_text(r"주소: \\server\share\dir") == _P(r"\\server\share\dir")
    assert parse_address_text("주소: 문서") is None                  # 라이브러리 표시 이름은 경로가 아님
    assert parse_address_text("주소 대역") is None and parse_address_text("") is None and parse_address_text(None) is None


def test_exists_in_tree(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    (tmp_path / "a" / "b" / "Target.PPTX").write_bytes(b"x")
    (tmp_path / ".git" / "hidden.txt").write_bytes(b"x")
    assert exists_in_tree(tmp_path, "target.pptx")                  # 대소문자 무관, 하위 폴더 깊숙이
    assert not exists_in_tree(tmp_path, "none.pptx")
    assert not exists_in_tree(tmp_path, "hidden.txt")               # 숨김 폴더는 제외
    assert not exists_in_tree(tmp_path / "없는폴더", "a")


def test_suggest_name_user_scenario_subfolder(tmp_path):
    """Chrome이 감지 폴더의 하위 폴더에서 저장 창을 열고 'xxx (1).pptx'를 제안하는 경우."""
    out = tmp_path / "다운로드" / "Claude_Output"
    out.mkdir(parents=True)
    (out / "DB접속우회접속차단방안.pptx").write_bytes(b"x")
    now = datetime(2026, 10, 11, 17, 30)
    # 창의 폴더(하위 폴더)를 알면 그 폴더에서 바로 판단
    assert suggest_name("DB접속우회접속차단방안 (1).pptx", out, now) == "DB접속우회접속차단방안_2026-10-11-1730.pptx"
    # 창의 폴더를 모르면 감지 폴더(부모) 전체에서 같은 이름을 찾는다
    assert suggest_name("DB접속우회접속차단방안 (1).pptx", tmp_path / "다운로드", now, search_tree=True) == \
        "DB접속우회접속차단방안_2026-10-11-1730.pptx"
    assert suggest_name("DB접속우회접속차단방안 (1).pptx", tmp_path / "다운로드", now) is None   # 폴더만 보면 못 찾음(예전 동작)
    assert suggest_name("다른문서 (1).pptx", tmp_path / "다운로드", now, search_tree=True) is None
    assert suggest_name("일반이름.pptx", out, now) is None

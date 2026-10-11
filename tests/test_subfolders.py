"""하위 폴더 감지: 실시간 감시, 폴더째 옮겨 온 경우, 숨김 폴더, 켜기/끄기, 놓친 파일 따라잡기."""
import os
import shutil
import time

import pytest

from download_catalog import catchup
from download_catalog.db import Database
from download_catalog.recorder import record_file
from download_catalog.settings import Settings
from download_catalog.watcher import (DownloadWatcher, WatchController, in_hidden_dir, iter_files)


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "dl"
    d.mkdir()
    return d


# ---- 도우미 ----
def test_iter_files_and_hidden_dirs(folder):
    (folder / "a.txt").write_bytes(b"1")
    (folder / "sub" / "deep").mkdir(parents=True)
    (folder / "sub" / "b.txt").write_bytes(b"2")
    (folder / "sub" / "deep" / "c.txt").write_bytes(b"3")
    (folder / ".git").mkdir()
    (folder / ".git" / "config").write_bytes(b"x")
    (folder / "sub" / ".cache").mkdir()
    (folder / "sub" / ".cache" / "z.txt").write_bytes(b"x")
    rel = lambda files: sorted(str(p.relative_to(folder)) for p in files)
    assert rel(iter_files(folder, recursive=True)) == ["a.txt", os.path.join("sub", "b.txt"),
                                                       os.path.join("sub", "deep", "c.txt")]
    assert rel(iter_files(folder, recursive=False)) == ["a.txt"]
    assert list(iter_files(folder / "없음", recursive=True)) == []
    assert in_hidden_dir(folder / ".git" / "config", folder)
    assert in_hidden_dir(folder / "sub" / ".cache" / "z.txt", folder)
    assert not in_hidden_dir(folder / "sub" / "b.txt", folder)
    assert not in_hidden_dir(folder / ".hidden.txt", folder)          # 파일 이름이 .으로 시작하는 것은 숨김 폴더가 아님
    assert not in_hidden_dir("D:/other/x.txt", folder)


# ---- 실시간 감시 ----
def test_watcher_detects_files_in_subfolders(folder):
    found = []
    c = WatchController(folder, lambda p: found.append(p.relative_to(folder).as_posix()), stable_for=0.4)
    c.start()
    try:
        (folder / "a" / "b").mkdir(parents=True)                      # 폴더가 먼저 생기고
        time.sleep(0.5)
        (folder / "top.txt").write_bytes(b"1")
        (folder / "a" / "mid.txt").write_bytes(b"2")
        (folder / "a" / "b" / "deep.txt").write_bytes(b"3")           # 2단계 아래
        assert wait_for(lambda: len(found) >= 3)
        assert sorted(found) == ["a/b/deep.txt", "a/mid.txt", "top.txt"]
    finally:
        c.stop()


def test_watcher_ignores_partial_and_hidden_in_subfolders(folder):
    found = []
    (folder / "sub").mkdir()
    (folder / ".git").mkdir()
    c = WatchController(folder, lambda p: found.append(p.name), stable_for=0.4)
    c.start()
    try:
        time.sleep(0.4)
        (folder / "sub" / "x.zip.crdownload").write_bytes(b"1")
        (folder / ".git" / "obj").write_bytes(b"2")
        (folder / "sub" / "ok.txt").write_bytes(b"3")
        assert wait_for(lambda: "ok.txt" in found)
        time.sleep(1.0)
        assert found == ["ok.txt"]
    finally:
        c.stop()


def test_chrome_style_rename_inside_subfolder(folder):
    found = []
    (folder / "sub").mkdir()
    c = WatchController(folder, lambda p: found.append(p.relative_to(folder).as_posix()), stable_for=0.4)
    c.start()
    try:
        time.sleep(0.4)
        part = folder / "sub" / "big.zip.crdownload"
        part.write_bytes(b"12345")
        part.rename(folder / "sub" / "big.zip")
        assert wait_for(lambda: found)
        time.sleep(0.8)
        assert found == ["sub/big.zip"]
    finally:
        c.stop()


def test_folder_moved_in_registers_its_files(tmp_path, folder):
    """폴더째 옮겨 오면 안의 파일에 대한 개별 이벤트가 오지 않으므로 폴더를 훑어서 올린다."""
    outside = tmp_path / "outside" / "pack"
    (outside / "inner").mkdir(parents=True)
    (outside / "one.txt").write_bytes(b"1")
    (outside / "inner" / "two.txt").write_bytes(b"22")
    found = []
    c = WatchController(folder, lambda p: found.append(p.relative_to(folder).as_posix()), stable_for=0.4)
    c.start()
    try:
        time.sleep(0.4)
        shutil.move(str(outside), str(folder / "pack"))
        assert wait_for(lambda: len(found) >= 2)
        assert sorted(found) == ["pack/inner/two.txt", "pack/one.txt"]
    finally:
        c.stop()


def test_paused_ignores_subfolders(folder):
    found = []
    (folder / "sub").mkdir()
    c = WatchController(folder, lambda p: found.append(p.name), stable_for=0.3)
    c.paused = True
    c.start()
    try:
        time.sleep(0.4)
        (folder / "sub" / "p.txt").write_bytes(b"1")
        time.sleep(1.5)
        assert found == []
    finally:
        c.stop()


# ---- 켜기/끄기 ----
def test_recursive_off_ignores_subfolders(folder):
    found = []
    (folder / "sub").mkdir()
    c = WatchController(folder, lambda p: found.append(p.relative_to(folder).as_posix()),
                        stable_for=0.4, recursive=False)
    c.start()
    try:
        time.sleep(0.4)
        (folder / "sub" / "hidden-from-us.txt").write_bytes(b"1")
        (folder / "top.txt").write_bytes(b"2")
        assert wait_for(lambda: "top.txt" in found)
        time.sleep(1.0)
        assert found == ["top.txt"]
    finally:
        c.stop()


def test_toggle_recursive_live_and_keeps_pause(folder):
    found = []
    (folder / "sub").mkdir()
    c = WatchController(folder, lambda p: found.append(p.relative_to(folder).as_posix()),
                        stable_for=0.4, recursive=False)
    c.start()
    try:
        time.sleep(0.4)
        c.set_recursive(True)                                          # 실행 중에 켠다
        assert c.recursive is True
        time.sleep(0.4)
        (folder / "sub" / "now.txt").write_bytes(b"1")
        assert wait_for(lambda: "sub/now.txt" in found)
        c.set_recursive(True)                                          # 같은 값이면 아무 일 없음
        c.set_recursive(False)                                         # 다시 끈다
        time.sleep(0.4)
        (folder / "sub" / "after-off.txt").write_bytes(b"2")
        (folder / "top2.txt").write_bytes(b"3")
        assert wait_for(lambda: "top2.txt" in found)
        time.sleep(0.8)
        assert "sub/after-off.txt" not in found
        c.paused = True
        c.set_recursive(True)
        assert c.paused is True                                        # 일시정지 상태가 새 감시에도 유지
        (folder / "sub" / "while-paused.txt").write_bytes(b"4")
        time.sleep(1.2)
        assert "sub/while-paused.txt" not in found
    finally:
        c.stop()


def test_setting_default_is_on(tmp_path):
    s = Settings(tmp_path / "s.json")
    assert s.get("watch_subfolders") is True
    s.set("watch_subfolders", False)
    s.save()
    assert Settings(tmp_path / "s.json").get("watch_subfolders") is False
    s.set("watch_subfolders", "yes")                                   # 잘못된 값은 기본값(켜짐)
    assert s.get("watch_subfolders") is True


# ---- 놓친 파일 따라잡기 / 기록 ----
def test_catchup_includes_subfolders_when_enabled(tmp_path, folder):
    db = Database(tmp_path / "c.db")
    since = time.time() - 5
    (folder / "sub" / ".hidden").mkdir(parents=True)
    (folder / "top.txt").write_bytes(b"1")
    (folder / "sub" / "inner.txt").write_bytes(b"22")
    (folder / "sub" / ".hidden" / "skip.txt").write_bytes(b"333")
    names = lambda r: sorted(p.relative_to(folder).as_posix() for p in catchup.find_candidates(folder, since, db, r))
    assert names(True) == ["sub/inner.txt", "top.txt"]
    assert names(False) == ["top.txt"]
    ids = catchup.run(folder, since, db, recursive=True)
    assert len(ids) == 2
    assert sorted(r["file_name"] for r in db.search("")) == ["inner.txt", "top.txt"]
    assert catchup.run(folder, since, db, recursive=True) == []        # 다시 돌려도 중복 없음


def test_record_in_subfolder_keeps_full_path_and_renames_within_it(tmp_path, folder):
    db = Database(tmp_path / "c.db")
    sub = folder / "projects" / "a"
    sub.mkdir(parents=True)
    (sub / "pkg.zip").write_bytes(b"v1")
    (folder / "pkg (1).zip").write_bytes(b"other folder: not a collision with sub/pkg.zip")
    dup = sub / "pkg (1).zip"
    dup.write_bytes(b"v2-new")
    rid, _ = record_file(db, dup, history_path=tmp_path / "none")
    row = db.get(rid)
    assert row["file_path"].startswith(str(sub))                      # 하위 폴더 경로가 그대로 기록
    assert row["file_name"].startswith("pkg_") and (sub / row["file_name"]).exists()   # 같은 폴더 안에서 이름 변경
    assert (folder / "pkg (1).zip").exists()                          # 다른 폴더의 같은 이름 파일은 건드리지 않음


def test_catchup_subfolder_since_limits_only_subfolder_files(tmp_path, folder):
    """하위 폴더 감지를 켜기 전에 생긴 하위 폴더 파일은 가져오지 않고, 최상위 파일은 기존 기준을 따른다."""
    db = Database(tmp_path / "c.db")
    (folder / "sub").mkdir()
    (folder / "old-top.txt").write_bytes(b"1")
    (folder / "sub" / "old-sub.txt").write_bytes(b"2")
    time.sleep(1.3)
    sub_since = time.time()                                       # 하위 폴더 감지를 켠 시각
    time.sleep(0.3)
    (folder / "new-top.txt").write_bytes(b"3")
    (folder / "sub" / "new-sub.txt").write_bytes(b"4")
    since = time.time() - 60                                      # 마지막 실행은 훨씬 전
    names = lambda **kw: sorted(p.name for p in catchup.find_candidates(folder, since, db, True, **kw))
    assert names() == ["new-sub.txt", "new-top.txt", "old-sub.txt", "old-top.txt"]            # 제한 없음
    assert names(subfolder_since=sub_since) == ["new-sub.txt", "new-top.txt", "old-top.txt"]  # old-sub만 빠짐
    assert names(subfolder_since=since - 1000) == names()         # 더 이른 값은 영향 없음


def test_subfolders_since_setting_roundtrip(tmp_path):
    s = Settings(tmp_path / "s.json")
    assert s.get("subfolders_since") is None
    s.set("subfolders_since", 1234.5)
    s.save()
    assert Settings(tmp_path / "s.json").get("subfolders_since") == 1234.5
    s.set("subfolders_since", "abc")
    assert s.get("subfolders_since") is None

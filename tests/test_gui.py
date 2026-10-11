"""화면(팝업·알림·카탈로그·목적 정리·환경설정·트레이 메뉴) 동작 시험. 실제 Tk 창을 띄운다."""
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from unittest import mock

import pytest

from download_catalog import catalog_window as cw_mod
from download_catalog import popup as popup_mod
from download_catalog import review_window as rv_mod
from download_catalog import settings_window as sw_mod
from download_catalog.catalog_window import CatalogWindow, NoteDialog, safe_geometry
from download_catalog.db import Database
from download_catalog.popup import PopupManager, describe, suggest_note, type_badge
from download_catalog.review_window import ReviewWindow
from download_catalog.settings import Settings
from download_catalog.settings_window import ListEditor, SettingsWindow
from download_catalog.toast import Toast
from download_catalog.tray import Tray, make_icon, summary_title


@pytest.fixture(scope="module")
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def env(tmp_path, root):
    db = Database(tmp_path / "c.db")
    settings = Settings(tmp_path / "s.json")
    return db, settings


def spin(root, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def key(root, widget, sequence):
    """위젯에 포커스를 준 뒤 키 입력을 보낸다(Tk는 키 이벤트에 포커스가 필요하다)."""
    widget.focus_force()
    root.update()
    widget.event_generate(sequence)
    root.update()


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def button(win, text):
    for w in walk(win):
        if isinstance(w, ttk.Button) and w.cget("text") == text:
            return w
    raise AssertionError(f"버튼 없음: {text}")


def has_button(win, text):
    return any(isinstance(w, ttk.Button) and w.cget("text") == text for w in walk(win))


def add(db, name, url=None, purpose="", when=None, size=1000, **kw):
    return db.add(file_name=name, base_name=name, file_path=f"C:/nope/{name}", sha256=name, size=size,
                  downloaded_at=when or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  source_url=url, purpose=purpose, **kw)


def popup_fields(win):
    combo = next(w for w in walk(win) if isinstance(w, ttk.Combobox))
    memo = next(w for w in walk(win) if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox))
    return combo, memo


def make_manager(root, db, settings, **kw):
    return PopupManager(root, db, settings, Toast(root), **kw)


# ---------------- 팝업 ----------------
def test_helpers():
    assert type_badge("a.zip")[0] == "ZIP" and type_badge("noext")[0] == "파일"
    assert describe({"version": 2}, "new", None) == "새 파일입니다"


def test_suggestion_priority(env):
    db, settings = env
    row = lambda rid: db.get(rid)
    first = add(db, "a.zip", "https://github.com/a")
    assert suggest_note(db, settings, row(first))[0] == "업무"                 # 기록 없음: 첫 목적
    other = add(db, "b.zip", "https://other.com/b", "개인")
    assert suggest_note(db, settings, row(first)) == ("개인", "", "")          # 마지막 목적
    done = add(db, "c.zip", "https://github.com/c", "개발")
    db.update_note(done, "개발", "소스")
    add(db, "d.zip", "https://other.com/d", "개인")
    nxt = add(db, "e.zip", "https://github.com/e")
    assert suggest_note(db, settings, row(nxt)) == ("개발", "소스", "※ github.com에서 지난번에: 개발")


def test_popup_prefill_and_save(root, env):
    db, settings = env
    done = add(db, "old.zip", "https://github.com/old", "개발")
    db.update_note(done, "개발", "소스 코드")
    new = add(db, "new.zip", "https://github.com/new")
    changed = []
    pm = make_manager(root, db, settings, on_change=lambda: changed.append(1))
    pm.notify(new, "new", None)
    win = pm._current
    combo, memo = popup_fields(win)
    assert combo.get() == "개발" and memo.get() == "소스 코드"             # 같은 사이트의 지난번 값
    assert any("지난번에: 개발" in w.cget("text") for w in walk(win) if isinstance(w, ttk.Label))
    assert [b for b in walk(win) if isinstance(b, ttk.Checkbutton)]        # 다시 묻지 않기
    combo.set("학습")
    memo.delete(0, "end")
    memo.insert(0, "수정")
    button(win, "저장 (Enter)").invoke()
    spin(root, 0.5)
    assert (db.get(new)["purpose"], db.get(new)["memo"]) == ("학습", "수정") and changed
    assert pm._current is None


def test_popup_enter_and_escape_keys(root, env):
    db, settings = env
    a, b = add(db, "a.zip"), add(db, "b.zip")
    pm = make_manager(root, db, settings)
    pm.notify(a, "new", None)
    win = pm._current
    key(root, popup_fields(win)[1], "<Return>")
    spin(root, 0.5)
    assert db.get(a)["purpose"] == "업무"                                  # Enter = 저장(기본 목적)
    pm.notify(b, "new", None)
    spin(root, 0.3)
    key(root, popup_fields(pm._current)[1], "<Escape>")
    spin(root, 0.5)
    assert db.get(b)["purpose"] == "" and pm._current is None             # Esc = 건너뛰기


def test_popup_exclude_domain_checkbox(root, env):
    db, settings = env
    rid = add(db, "a.zip", "https://spam.com/a.zip")
    got = []
    pm = make_manager(root, db, settings, on_exclude_domain=got.append)
    pm.notify(rid, "new", None)
    check = next(w for w in walk(pm._current) if isinstance(w, ttk.Checkbutton))
    check.invoke()
    button(pm._current, "건너뛰기 (Esc)").invoke()
    spin(root, 0.4)
    assert got == ["spam.com"]


def test_popup_same_purpose_for_rest(root, env):
    db, settings = env
    ids = [add(db, f"{i}.zip") for i in range(4)]
    pm = make_manager(root, db, settings)
    pm.notify(ids[0], "new", None)                    # 팝업이 먼저 뜨고
    win = pm._current
    assert not has_button(win, "나머지 1개도 같은 목적으로")
    for i in ids[1:]:                                  # 입력하는 동안 파일이 더 들어옴
        pm.notify(i, "new", None)
        spin(root, 0.05)
    assert has_button(win, "나머지 3개도 같은 목적으로")   # 버튼이 나타나고 개수가 갱신됨
    assert [b.cget("text") for b in walk(win) if isinstance(b, ttk.Button)][-2:] == ["건너뛰기 (Esc)", "저장 (Enter)"]
    combo, _ = popup_fields(win)
    combo.set("학습")
    button(win, "나머지 3개도 같은 목적으로").invoke()
    spin(root, 0.5)
    assert [db.get(i)["purpose"] for i in ids] == ["학습"] * 4 and pm._current is None


def test_popup_duplicate_banner_and_delete(root, env):
    db, settings = env
    orig = add(db, "x.zip")
    dup = add(db, "x (1).zip", duplicate_of=orig)
    pm = make_manager(root, db, settings)
    pm.notify(dup, "duplicate", db.get(orig))
    banner = next(w for w in walk(pm._current) if isinstance(w, tk.Label) and "이미 받은 파일" in str(w.cget("text")))
    assert banner.cget("bg") == "#fef3c7"                                  # 눈에 띄는 배경색
    button(pm._current, "기록 삭제").invoke()
    spin(root, 0.4)
    assert db.get(dup) is None


def test_popup_url_details_toggle(root, env):
    db, settings = env
    rid = add(db, "a.zip", "https://drive.google.com/download?id=1&at=SECRET")
    pm = make_manager(root, db, settings)
    pm.notify(rid, "new", None)
    win = pm._current
    labels = lambda: [w for w in walk(win) if isinstance(w, ttk.Label) and "SECRET" in str(w.cget("text"))]
    assert not any(w.winfo_ismapped() for w in labels())                   # 기본은 도메인만
    toggle = next(w for w in walk(win) if isinstance(w, tk.Label) and "자세히" in str(w.cget("text")))
    spin(root, 0.2)                                                        # 창이 그려진 뒤여야 클릭이 전달된다
    toggle.event_generate("<Button-1>")
    spin(root, 0.2)
    assert labels() and labels()[0].winfo_ismapped()
    button(win, "건너뛰기 (Esc)").invoke()
    spin(root, 0.3)


def test_popup_autoskip(root, env):
    db, settings = env
    settings.set("autoskip_seconds", 1)
    rid = add(db, "a.zip")
    pm = make_manager(root, db, settings)
    pm.notify(rid, "new", None)
    assert pm._current is not None
    spin(root, 2.6)
    assert pm._current is None and db.get(rid)["purpose"] == ""            # 입력 없이 자동 건너뛰기


def test_popup_mode_quiet_and_off(root, env):
    db, settings = env
    a, b = add(db, "a.zip"), add(db, "b.zip")
    pm = make_manager(root, db, settings)
    settings.set("popup_mode", "off")
    pm.notify(a, "new", None)
    assert pm._current is None and pm.toast.win is None
    settings.set("popup_mode", "quiet")
    pm.notify(a, "new", None)
    assert pm._current is None and pm.toast.win is not None               # 알림만, 입력창은 안 뜸
    pm.notify(b, "new", None)
    texts = [w.cget("text") for w in walk(pm.toast.win) if isinstance(w, tk.Label)]
    assert any("2개" in t for t in texts)
    spin(root, 0.2)
    next(iter(pm.toast.win.children.values())).event_generate("<Button-1>")
    spin(root, 0.4)
    assert pm._current is not None                                         # 클릭하면 입력창이 열림
    button(pm._current, "건너뛰기 (Esc)").invoke()
    spin(root, 0.4)
    button(pm._current, "건너뛰기 (Esc)").invoke()
    spin(root, 0.4)
    assert pm._current is None


def test_toast_auto_closes(root):
    t = Toast(root)
    t.show("안녕", seconds=0.3)
    assert t.win is not None
    spin(root, 0.8)
    assert t.win is None


# ---------------- 카탈로그 창 ----------------
def catalog(root, db, settings):
    c = CatalogWindow(root, db, settings)
    c.show()
    root.update()
    return c


def names(c):
    return [c.tree.set(i, "file_name") for i in c.tree.get_children()]


def test_catalog_columns_and_sorting(root, env):
    db, settings = env
    add(db, "b.zip", "https://github.com/b", "개발", when="2026-10-01 10:00:00", size=2048)
    add(db, "a.zip", "https://site.com/a", "", when="2026-10-03 10:00:00", size=10)
    add(db, "c.zip", None, "학습", when="2026-10-02 10:00:00", size=5_000_000, version=3)
    c = catalog(root, db, settings)
    assert [c.tree.heading(k)["text"].strip(" ▲▼") for k in c.tree["columns"]] == [
        "받은 시각", "파일명", "버전", "목적", "메모", "도메인", "크기", "상태"]
    assert names(c) == ["a.zip", "c.zip", "b.zip"]                         # 기본: 최신순
    row = c.tree.item(c.tree.get_children()[2])["values"]
    assert row[5] == "github.com" and row[6] == "2.0 KB" and row[7] == "없음"
    c.sort_by("file_name")
    assert names(c) == ["c.zip", "b.zip", "a.zip"] or names(c) == ["a.zip", "b.zip", "c.zip"]
    c.sort_by("file_name")
    first = names(c)
    c.sort_by("file_name")
    assert names(c) == list(reversed(first))                               # 같은 열을 또 누르면 순서 반대
    c.sort_by("size")
    assert names(c) == ["c.zip", "b.zip", "a.zip"]                         # 크기 내림차순(큰 것 먼저)
    c.sort_by("version")
    assert names(c)[0] == "c.zip"
    assert "▼" in c.tree.heading("version")["text"]
    c.close()


def test_catalog_filters_and_status(root, env):
    db, settings = env
    old = "2026-01-01 10:00:00"
    add(db, "today.zip", "https://github.com/x", "개발")
    add(db, "old.zip", None, "", when=old)
    v2 = add(db, "v2.zip", None, "개발", version=2)
    add(db, "dup.zip", None, "", duplicate_of=v2)
    c = catalog(root, db, settings)
    assert len(names(c)) == 4 and "총 4건 중 4건 표시" in c.status.get()
    c.query.set("github")
    c.refresh()
    assert names(c) == ["today.zip"]
    c.query.set("")
    c.period.set("오늘")
    c.refresh()
    assert "old.zip" not in names(c)
    c.period.set("전체 기간")
    c.purpose_filter.set("개발")
    c.refresh()
    assert sorted(names(c)) == ["today.zip", "v2.zip"]
    c.purpose_filter.set("전체 목적")
    c.only_unfilled.set(True)
    c.refresh()
    assert sorted(n.replace(" (중복)", "") for n in names(c)) == ["dup.zip", "old.zip"]
    c.only_unfilled.set(False)
    c.only_new_version.set(True)
    c.refresh()
    assert names(c) == ["v2.zip"]
    c.only_new_version.set(False)
    c.hide_dups.set(True)
    c.refresh()
    assert "dup.zip (중복)" not in names(c) and "총 4건 중 3건 표시" in c.status.get()
    c.close()


def test_catalog_banner_unfilled(root, env):
    db, settings = env
    r = add(db, "a.zip")
    c = catalog(root, db, settings)
    assert c.banner.winfo_ismapped() and "1건" in c.banner_label.cget("text")
    db.update_note(r, "업무", "")
    c.refresh()
    root.update()
    assert not c.banner.winfo_ismapped()
    c.close()


def test_catalog_keyboard_and_multi_delete(root, env):
    db, settings = env
    for i in range(5):
        add(db, f"{i}.zip")
    c = catalog(root, db, settings)
    c.tree.focus_set()
    c._select_all()
    assert len(c.tree.selection()) == 5
    c.tree.selection_set(c.tree.get_children()[:3])
    with mock.patch.object(cw_mod.messagebox, "askyesno", return_value=True) as ask:
        key(root, c.tree, "<Delete>")
        assert "3개" in ask.call_args.args[1]
    assert len(names(c)) == 2
    with mock.patch.object(cw_mod.messagebox, "askyesno", return_value=False):
        c.tree.selection_set(c.tree.get_children()[0])
        c.delete_selected()
    assert len(names(c)) == 2
    c.close()


def test_catalog_bulk_edit_purpose(root, env):
    db, settings = env
    ids = [add(db, f"{i}.zip", purpose="", ) for i in range(3)]
    db.update_note(ids[0], "", "원래 메모")
    c = catalog(root, db, settings)
    c.tree.selection_set(c.tree.get_children())
    captured = {}
    with mock.patch.object(cw_mod, "NoteDialog", side_effect=lambda *a, **k: captured.update(k, args=a)):
        c.edit_selected()
    assert captured["count"] == 3
    captured["on_ok"]("학습", None)                                         # 메모는 그대로 두고 목적만
    assert [db.get(i)["purpose"] for i in ids] == ["학습"] * 3 and db.get(ids[0])["memo"] == "원래 메모"
    c.tree.selection_set(c.tree.get_children())
    c.edit_selected.__func__  # noqa  (존재 확인)
    c.close()


def test_note_dialog_modes(root):
    got = []
    d = NoteDialog(root, ["업무", "학습"], purpose="업무", memo="m", count=1, on_ok=lambda p, m: got.append((p, m)))
    d.purpose.set("학습")
    d._ok()
    assert got == [("학습", "m")]
    d = NoteDialog(root, ["업무"], count=4, on_ok=lambda p, m: got.append((p, m)))
    assert str(d.memo.cget("state")) == "disabled"
    d.purpose.set("업무")
    d._ok()
    assert got[-1] == ("업무", None)                                       # 여러 건: 메모 변경 안 함
    d = NoteDialog(root, ["업무"], count=4, on_ok=lambda p, m: got.append((p, m)))
    d.change_memo.set(True)
    d._toggle_memo()
    d.memo.insert(0, "공통")
    d._ok()
    assert got[-1] == ("", "공통")


def test_catalog_context_menu_and_copy_url(root, env):
    db, settings = env
    add(db, "a.zip", "https://github.com/a?x=1")
    c = catalog(root, db, settings)
    labels = [c.menu.entrycget(i, "label") for i in range(c.menu.index("end") + 1) if c.menu.type(i) == "command"]
    assert labels == ["파일 열기 (Enter)", "폴더 열기", "주소 복사", "목적/메모 수정", "기록 삭제 (Delete)"]
    c.tree.selection_set(c.tree.get_children()[0])
    c.copy_url()
    assert root.clipboard_get() == "https://github.com/a?x=1"
    c.close()


def test_catalog_search_shortcuts(root, env):
    db, settings = env
    add(db, "a.zip")
    c = catalog(root, db, settings)
    c.query.set("zzz")
    c.refresh()
    assert names(c) == []
    c._clear_search()
    assert names(c) == ["a.zip"]
    c.win.focus_force()
    c.tree.focus_set()
    root.update()
    key(root, c.win, "<Control-f>")                                        # Ctrl+F: 검색칸으로 이동
    assert root.focus_get() is c.search_entry
    c.close()


def test_catalog_remembers_window_state(root, env, tmp_path):
    db, settings = env
    add(db, "a.zip")
    c = catalog(root, db, settings)
    c.win.geometry("900x500+40+40")
    root.update()
    c.tree.column("memo", width=333)
    c.sort_by("file_name")
    c.close()
    saved = Settings(tmp_path / "s.json").get("catalog")
    assert saved["geometry"].startswith("900x500") and saved["widths"]["memo"] == 333
    assert saved["sort"] == ["file_name", False]
    c2 = CatalogWindow(root, db, Settings(tmp_path / "s.json"))
    c2.show()
    assert int(c2.tree.column("memo", "width")) == 333 and c2.sort_key == "file_name"
    c2.close()


def test_safe_geometry():
    assert safe_geometry("900x500+40+40", 1920, 1080) == "900x500+40+40"
    assert safe_geometry("900x500+3000+40", 1920, 1080) == "900x500"      # 화면 밖 위치는 버림
    assert safe_geometry("5000x3000+0+0", 1920, 1080) == "1920x1080+0+0"
    assert safe_geometry("엉터리", 1920, 1080) == cw_mod.DEFAULT_GEOMETRY
    assert safe_geometry(None, 1920, 1080) == cw_mod.DEFAULT_GEOMETRY


# ---------------- 목적 정리(U3) ----------------
def test_review_flow(root, env):
    db, settings = env
    ids = [add(db, f"{i}.zip", "https://github.com/x") for i in range(3)]
    done = add(db, "filled.zip", purpose="업무")
    skipped = add(db, "skip.png", auto_skipped=1)
    rv = ReviewWindow(root, db, settings)
    with mock.patch.object(rv_mod.messagebox, "showinfo") as info:
        rv.show()
        assert rv.ids == ids[::-1]                                         # 미입력만, 최신순
        assert rv.counter.cget("text") == "1 / 3" and rv.name.cget("text") == "2.zip"
        rv.purpose.set("학습")
        rv.memo.insert(0, "하나")
        key(root, rv.memo, "<Return>")                                     # Enter: 저장 후 다음
        assert (db.get(ids[2])["purpose"], db.get(ids[2])["memo"]) == ("학습", "하나")
        assert rv.counter.cget("text") == "2 / 3"
        rv.skip()
        assert rv.counter.cget("text") == "3 / 3"
        rv.back()
        assert rv.counter.cget("text") == "2 / 3"
        rv.skip()
        rv.save_next()                                                     # 마지막 -> 끝
        assert info.called and rv.win is None
    assert db.get(ids[1])["purpose"] == "" and db.get(ids[0])["purpose"] == "학습"   # 건너뛴 것은 그대로, 마지막은 기본값 저장
    assert db.get(skipped)["purpose"] == "" and db.get(done)["purpose"] == "업무"


def test_review_empty(root, env):
    db, settings = env
    rv = ReviewWindow(root, db, settings)
    with mock.patch.object(rv_mod.messagebox, "showinfo") as info:
        rv.show()
    assert info.called and rv.win is None


# ---------------- 환경설정 ----------------
def test_list_editor(root):
    root_frame = tk.Toplevel(root)
    ed = ListEditor(root_frame, reorder=True)
    ed.set_items(["a", "b", "c"])
    ed.entry.insert(0, " d ")
    ed.add()
    ed.entry.insert(0, "a")
    ed.add()                                                               # 중복은 추가 안 함
    assert ed.items() == ["a", "b", "c", "d"]
    ed.listbox.selection_set(3)
    ed.move(-1)
    assert ed.items() == ["a", "b", "d", "c"]
    ed.listbox.selection_clear(0, "end")
    ed.listbox.selection_set(0)
    ed.remove()
    assert ed.items() == ["b", "d", "c"]
    root_frame.destroy()


def settings_window(root, db, settings, tmp_path, applied):
    folder = tmp_path / "watch"
    folder.mkdir(exist_ok=True)
    sw = SettingsWindow(root, settings, db, tmp_path, lambda: folder, applied.append, is_autostart=lambda: True)
    sw.show()
    root.update()
    return sw, folder


def test_settings_window_collect_and_apply(root, env, tmp_path):
    db, settings = env
    applied = []
    sw, folder = settings_window(root, db, settings, tmp_path, applied)
    tabs = [sw.win.nametowidget(t) for t in sw.win.winfo_children()[0].winfo_children()[0].tabs()]
    nb = sw.win.winfo_children()[0].winfo_children()[0]
    assert [nb.tab(i, "text").strip() for i in range(len(nb.tabs()))] == ["일반", "팝업", "제외 규칙", "정보"]
    assert sw.path_var.get() == str(folder) and sw.autostart_var.get() is True
    sw.mode_var.set("quiet")
    sw.auto_var.set(True)
    sw.secs_var.set(45)
    sw.minsize_var.set("1.5")
    sw.exts_editor.set_items(["png"])
    sw.domains_editor.set_items(["spam.com"])
    sw.purposes_editor.set_items(["A", "B"])
    sw.font_var.set("아주 크게")
    sw.autostart_var.set(False)
    values, error = sw.collect()
    assert error is None
    assert sw.sub_var.get() is True                                        # 하위 폴더 감지: 기본 켜짐
    assert values == {"watch_dir": folder, "watch_subfolders": True, "autostart": False, "list_font_size": 14, "popup_mode": "quiet",
                      "autoskip_seconds": 45, "purposes": ["A", "B"], "min_size_mb": 1.5,
                      "exclude_exts": ["png"], "exclude_domains": ["spam.com"]}
    button(sw.win, "저장").invoke()
    assert applied == [values] and not sw.win.winfo_exists()


def test_settings_window_validation(root, env, tmp_path):
    db, settings = env
    applied = []
    sw, folder = settings_window(root, db, settings, tmp_path, applied)
    sw.path_var.set(str(tmp_path / "없는폴더"))
    assert sw.collect()[1].startswith("폴더를 찾을 수 없습니다")
    sw.path_var.set(str(folder))
    sw.minsize_var.set("abc")
    assert "숫자" in sw.collect()[1]
    sw.minsize_var.set("-1")
    assert "숫자" in sw.collect()[1]
    sw.minsize_var.set("0")
    sw.auto_var.set(True)
    sw.secs_var.set(1)
    assert "5~600" in sw.collect()[1]
    sw.auto_var.set(False)
    sw.purposes_editor.set_items([])
    assert "비어" in sw.collect()[1]
    sw.purposes_editor.set_items(["x"])
    with mock.patch.object(sw_mod.messagebox, "showerror") as err:
        sw.path_var.set(str(tmp_path / "x"))
        button(sw.win, "저장").invoke()
        assert err.called and sw.win.winfo_exists() and applied == []     # 잘못된 값이면 창 유지
        sw.path_var.set(str(folder))
        sw.on_apply = mock.Mock(side_effect=RuntimeError("실패"))
        button(sw.win, "저장").invoke()
        assert err.call_count == 2 and sw.win.winfo_exists()               # 적용 실패해도 창 유지
    sw.win.destroy()


def test_settings_window_info_tab_and_backup(root, env, tmp_path):
    db, settings = env
    add(db, "a.zip")
    sw, _ = settings_window(root, db, settings, tmp_path, [])
    texts = [w.cget("text") for w in walk(sw.win) if isinstance(w, ttk.Label)]
    assert "1.0.0" in texts or any(t[0].isdigit() and "." in t for t in texts)
    assert "1건" in texts
    assert "개발자" in texts and "일등감자 (" in texts                          # 정보 탭의 개발자 정보
    assert sw.mail_link.cget("text") == "deepstack.owen@gmail.com" and str(sw.mail_link.cget("cursor")) == "hand2"
    dest = tmp_path / "bk.db"
    with mock.patch.object(sw_mod.filedialog, "asksaveasfilename", return_value=str(dest)), \
         mock.patch.object(sw_mod.messagebox, "showinfo"):
        button(sw.win, "기록 백업 만들기...").invoke()
    assert Database(dest).count_all() == 1
    sw.win.destroy()


# ---------------- 트레이 ----------------
def test_tray_icon_images_and_title():
    normal, paused = make_icon(False), make_icon(True)
    assert normal.size == paused.size == (64, 64) and normal.getpixel((32, 6)) != paused.getpixel((32, 6))
    assert summary_title(5, 3, False) == "Download Catalog\n오늘 5건 기록 / 목적 안 쓴 것 3건"
    assert "일시정지" in summary_title(0, 0, True)


def test_tray_menu_items(env):
    import queue
    db, settings = env
    events = queue.Queue()
    paused = {"v": False}
    tray = Tray(db, events, lambda: paused["v"], lambda: paused.update(v=not paused["v"]))
    items = list(tray._recent_items())
    assert len(items) == 1 and not items[0].enabled                        # 기록 없음
    for i in range(7):
        add(db, f"file{i}.zip")
    items = list(tray._recent_items())
    assert [i.text for i in items] == [f"file{n}.zip" for n in (6, 5, 4, 3, 2)]   # 최근 5개, 최신순
    items[0](tray.icon)
    assert events.get_nowait() == ("open_folder", "C:/nope/file6.zip")
    menu = list(tray.icon.menu.items)
    texts = [m.text for m in menu if m is not pystray_sep()]
    assert "카탈로그 열기" in texts and "환경설정" in texts and "종료" in texts
    unfilled_item = next(m for m in menu if m.text.startswith("목적 안 쓴 기록 정리"))
    assert unfilled_item.text == "목적 안 쓴 기록 정리 (7건)" and unfilled_item.visible
    tray.icon.title = "x"
    tray.refresh()                                                         # 실행 전에도 오류 없이 동작
    tray.toggle_pause()
    assert paused["v"] is True


def pystray_sep():
    import pystray
    return pystray.Menu.SEPARATOR


def test_settings_window_subfolder_checkbox(root, env, tmp_path):
    db, settings = env
    applied = []
    settings.set("watch_subfolders", False)                                # 저장된 값이 화면에 반영되는지
    sw, folder = settings_window(root, db, settings, tmp_path, applied)
    assert sw.sub_var.get() is False
    check = next(w for w in walk(sw.win) if isinstance(w, ttk.Checkbutton) and "하위 폴더" in str(w.cget("text")))
    check.invoke()                                                         # 켜기
    assert sw.collect()[0]["watch_subfolders"] is True
    check.invoke()                                                         # 끄기
    assert sw.collect()[0]["watch_subfolders"] is False
    sw.win.destroy()


def test_developer_email_link_opens_mail(root, env, tmp_path):
    db, settings = env
    sw, _ = settings_window(root, db, settings, tmp_path, [])
    sw.win.winfo_children()[0].winfo_children()[0].select(3)                # 정보 탭을 보이게 해야 클릭이 전달된다
    spin(root, 0.3)
    with mock.patch.object(sw_mod.os, "startfile") as start:
        sw.mail_link.event_generate("<Button-1>")                          # 메일 주소를 누르면
        spin(root, 0.2)
        assert start.call_count == 1
        url = start.call_args.args[0]
        assert url.startswith("mailto:deepstack.owen@gmail.com?subject=")        # 개발자에게 보내는 새 메일
        assert "%EB%AC%B8%EC%9D%98" in url                                  # 제목(한글 '문의')이 주소 형식으로 인코딩됨
    with mock.patch.object(sw_mod.os, "startfile", side_effect=OSError("no mail client")),          mock.patch.object(sw_mod.messagebox, "showinfo") as info:
        sw.send_mail()                                                      # 메일 프로그램이 없으면
        assert info.called and root.clipboard_get() == "deepstack.owen@gmail.com"   # 주소를 복사하고 안내
    sw.win.destroy()

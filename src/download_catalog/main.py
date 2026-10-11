"""트레이 상주 프로그램의 시작점.

스레드 구성: tkinter(팝업·카탈로그 창)는 메인 스레드, 트레이(pystray)와 폴더 감시·
놓친 파일 따라잡기는 별도 스레드. 다른 스레드의 요청은 queue를 거쳐 메인 스레드가 처리한다.
"""
import argparse
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from . import autostart, catchup, rules
from .catalog_window import CatalogWindow, open_in_explorer
from .db import Database
from .popup import PopupManager
from .recorder import record_file
from .review_window import ReviewWindow
from .savedialog import SaveDialogFixer
from .settings import Settings, default_watch_dir
from .settings_window import SettingsWindow
from .single_instance import SingleInstance
from .toast import Toast
from .tray import Tray
from .tray_promote import promote_when_ready
from .watcher import WatchController

FIRST_RUN_IMPORT_DAYS = 30
TICK_SECONDS = 60


def default_data_dir():
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "DownloadCatalog"


def catchup_start_time(settings, db, now, first_run_choice):
    """놓친 파일을 찾을 기준 시각(epoch 초).

    first_run_choice: 처음 설치 때 '기존 파일도 기록'을 골랐는지(True/False), 해당 없으면 None.
    """
    if first_run_choice is True:
        return now - FIRST_RUN_IMPORT_DAYS * 86400
    if first_run_choice is False:
        return now
    last_run = settings.get("last_run")
    if last_run:
        return last_run
    latest = db.latest_downloaded_at()   # 이전 버전에서 올라온 사용자: 마지막 기록 이후 파일부터
    if latest:
        try:
            return datetime.strptime(latest, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            pass
    return now


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download Catalog")
    parser.add_argument("--downloads-dir", type=Path, default=None,
                        help="감지 폴더(지정하면 환경설정보다 우선, 테스트용)")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--history-path", type=Path, default=None,
                        help="Chrome History DB 경로(테스트용)")
    parser.add_argument("--no-tray", action="store_true", help="트레이 없이 실행(테스트용)")
    parser.add_argument("--no-lock", action="store_true", help="중복 실행 방지 끄기(테스트용)")
    parser.add_argument("--no-first-run-dialog", action="store_true",
                        help="처음 실행 때 기존 파일 가져오기 질문을 하지 않음(테스트용)")
    args = parser.parse_args(argv)

    instance = None if args.no_lock else SingleInstance()
    if instance is not None and instance.already_running:
        instance.signal_existing()   # 이미 켜진 프로그램의 카탈로그 창을 앞으로 띄워 달라고 알림
        instance.close()
        print("이미 실행 중입니다. 실행 중인 프로그램의 카탈로그를 엽니다.")
        return 1

    db = Database(args.data_dir / "catalog.db")
    settings = Settings(args.data_dir / "settings.json")
    watch_dir = args.downloads_dir or settings.watch_dir
    if not watch_dir.is_dir():  # 저장된 폴더가 사라졌으면(드라이브 분리 등) 기본 폴더로
        print(f"감지 폴더를 찾을 수 없어 기본 폴더를 씁니다: {watch_dir}", flush=True)
        watch_dir = default_watch_dir()
    events = queue.Queue()  # 다른 스레드 -> 메인 스레드
    tray = None

    root = tk.Tk()
    root.withdraw()
    toast = Toast(root)

    def after_change():
        """기록이 바뀌었을 때(메인 스레드): 열려 있는 창과 트레이를 최신으로."""
        catalog.refresh()
        if tray is not None:
            tray.refresh()

    def add_excluded_domain(domain):
        domains = settings.get("exclude_domains")
        if domain not in domains:
            domains.append(domain)
            settings.set("exclude_domains", domains)
            settings.save()
            toast.show(f"앞으로 {domain}에서 받은 파일은\n묻지 않고 기록만 합니다.",
                       on_click=settings_window.show, hint="클릭하면 환경설정에서 바꿀 수 있어요")

    catalog = CatalogWindow(root, db, settings)
    catalog.on_change = after_change
    popups = PopupManager(root, db, settings, toast, on_change=after_change,
                          on_exclude_domain=add_excluded_domain)
    review = ReviewWindow(root, db, settings, on_change=after_change)
    catalog.on_review = review.show

    def on_file(path):
        """감시 스레드에서 호출: 기록 먼저, 팝업은 메인 스레드에 요청."""
        try:
            result = record_file(db, path, args.history_path)
            if result is None:
                return
            record_id, judgement = result
            row = db.get(record_id)
            if rules.prompt_excluded(settings, row["file_name"], row["size"], row["domain"]):
                db.set_auto_skipped(record_id)   # 제외 규칙: 기록만 하고 팝업은 생략
                events.put(("refresh",))
                return
        except Exception:
            traceback.print_exc()
            return
        events.put(("new_record", record_id, judgement.kind, judgement.related))

    watcher = WatchController(watch_dir, on_file, recursive=settings.get("watch_subfolders"))
    watcher.start()
    save_dialog = SaveDialogFixer(watch_dir, is_paused=lambda: watcher.paused,
                                  get_dir=lambda: watcher.folder)
    save_dialog.start()

    def apply_settings(values):
        """환경설정 창에서 호출: 폴더 변경을 먼저 시도(실패하면 나머지는 바꾸지 않음)."""
        watcher.set_folder(values["watch_dir"])
        was_on = watcher.recursive
        watcher.set_recursive(values["watch_subfolders"])
        if values["watch_subfolders"] and not was_on:
            settings.set("subfolders_since", time.time())   # 지금부터가 하위 폴더 감지 시작
        elif not values["watch_subfolders"]:
            settings.set("subfolders_since", None)
        settings.watch_dir = values["watch_dir"]
        settings.set("watch_subfolders", values["watch_subfolders"])
        autostart.set_enabled(values["autostart"])
        font_changed = values["list_font_size"] != settings.get("list_font_size")
        for key in ("list_font_size", "popup_mode", "autoskip_seconds", "purposes",
                    "min_size_mb", "exclude_exts", "exclude_domains"):
            settings.set(key, values[key])
        settings.save()
        if font_changed and catalog.alive():   # 글자 크기는 창을 다시 열어야 바뀐다
            catalog.close()
            catalog.show()
        after_change()
        print(f"설정 적용: 감지 폴더 {values['watch_dir']}", flush=True)

    settings_window = SettingsWindow(root, settings, db, args.data_dir, lambda: watcher.folder,
                                     apply_settings, is_autostart=autostart.is_enabled)
    catalog.on_settings = settings_window.show

    def toggle_pause():
        watcher.paused = not watcher.paused
        if tray is not None:
            tray.refresh()

    # ---- 놓친 파일 따라잡기(F1) ----
    def start_catchup():
        first = not settings.get("first_run_done")
        choice = None
        if first and db.count_all() == 0:
            if args.no_first_run_dialog:
                choice = False
            else:
                choice = messagebox.askyesno(
                    "Download Catalog - 처음 실행",
                    f"감지 폴더에 이미 있는 파일 중 최근 {FIRST_RUN_IMPORT_DAYS}일 안에 받은 파일도\n"
                    "기록에 넣을까요?\n\n(목적은 비어 있는 상태로 들어가며, 나중에 '목적 안 쓴 기록'에서\n"
                    "하나씩 입력할 수 있습니다.)\n\n폴더: " + str(watch_dir))
        now = time.time()
        since = catchup_start_time(settings, db, now, choice)
        # 하위 폴더 감지가 언제부터인지: 꺼져 있으면 비우고, 처음 켜지는 시점이면 지금(최초 실행에서 기존 파일 가져오기를
        # 고른 경우에는 그 기준 시각)부터로 정한다. 이전에 생긴 하위 폴더 파일을 거슬러 가져오지 않기 위함.
        if not watcher.recursive:
            settings.set("subfolders_since", None)
        elif settings.get("subfolders_since") is None:
            settings.set("subfolders_since", since if choice is True else now)
        sub_since = settings.get("subfolders_since")
        settings.set("first_run_done", True)
        settings.set("last_run", now)
        settings.save()

        def work():
            try:
                ids = catchup.run(watcher.folder, since, db, args.history_path,
                                  recursive=watcher.recursive, subfolder_since=sub_since)
                for record_id in ids:
                    row = db.get(record_id)
                    if row and rules.prompt_excluded(settings, row["file_name"], row["size"], row["domain"]):
                        db.set_auto_skipped(record_id)
                events.put(("catchup_done", len(ids)))
            except Exception:
                traceback.print_exc()

        threading.Thread(target=work, daemon=True).start()

    # ---- 이벤트 처리(메인 스레드) ----
    def pump():
        try:
            while True:
                item = events.get_nowait()
                kind = item[0]
                if kind == "new_record":
                    popups.notify(item[1], item[2], item[3])
                    after_change()
                elif kind == "refresh":
                    after_change()
                elif kind == "catalog":
                    catalog.show()
                    catalog.win.lift()
                elif kind == "review":
                    review.show()
                elif kind == "settings":
                    settings_window.show()
                elif kind == "open_folder":
                    open_in_explorer(item[1])
                elif kind == "catchup_done":
                    after_change()
                    if item[1]:
                        toast.show(f"{item[1]}개 파일을 새로 기록했어요\n(목적은 비어 있습니다)",
                                   on_click=review.show, hint="클릭하면 목적을 하나씩 입력합니다")
                elif kind == "quit":
                    shutdown()
                    return
        except queue.Empty:
            pass
        root.after(300, pump)

    def tick():
        """주기 작업: 마지막 실행 시각 기록(놓친 파일 따라잡기용), 트레이 문구 갱신."""
        settings.set("last_run", time.time())
        try:
            settings.save()
        except OSError:
            pass
        if tray is not None:
            tray.refresh()
        root.after(TICK_SECONDS * 1000, tick)

    def shutdown():
        settings.set("last_run", time.time())
        try:
            settings.save()
        except OSError:
            pass
        save_dialog.stop()
        watcher.stop()
        if tray is not None:
            tray.stop()
        if instance is not None:
            instance.close()
        root.quit()

    if not args.no_tray:
        tray = Tray(db, events, lambda: watcher.paused, toggle_pause)
        tray.start()
        promote_when_ready()  # 숨겨진 아이콘 칸에 가려지지 않고 바로 보이게
        tray.refresh()
    if instance is not None:
        instance.listen(lambda: events.put(("catalog",)))   # 두 번째 실행 -> 카탈로그 창 열기

    print(f"감시 시작: {watch_dir}  / 기록: {args.data_dir / 'catalog.db'}", flush=True)
    root.after(300, pump)
    root.after(TICK_SECONDS * 1000, tick)
    root.after(500, start_catchup)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

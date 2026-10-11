"""트레이 아이콘: 일시정지 표시, 마우스를 올리면 요약, 최근 받은 파일 메뉴."""
from PIL import Image, ImageDraw
import pystray


def make_icon(paused=False):
    """파란 원 + 아래 화살표. 일시정지 중이면 회색 원 + 정지 표시."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    if paused:
        d.ellipse((2, 2, 62, 62), fill=(107, 114, 128, 255))
        d.rectangle((20, 18, 28, 46), fill=white)
        d.rectangle((36, 18, 44, 46), fill=white)
    else:
        d.ellipse((2, 2, 62, 62), fill=(37, 99, 235, 255))
        d.polygon([(32, 46), (18, 30), (26, 30), (26, 14), (38, 14), (38, 30), (46, 30)], fill=white)
        d.rectangle((18, 49, 46, 53), fill=white)
    return img


def summary_title(today, unfilled, paused):
    head = "Download Catalog (일시정지 중)" if paused else "Download Catalog"
    return f"{head}\n오늘 {today}건 기록 / 목적 안 쓴 것 {unfilled}건"


class Tray:
    def __init__(self, db, events, is_paused, toggle_pause):
        self.db, self.events = db, events
        self.is_paused, self.toggle_pause = is_paused, toggle_pause
        self.icon = pystray.Icon("download_catalog", make_icon(False), "Download Catalog",
                                 menu=self._build_menu())

    def start(self):
        self.icon.run_detached()

    def stop(self):
        self.icon.stop()

    def refresh(self):
        """아이콘 모양·마우스 올렸을 때 문구·메뉴(미입력 개수, 최근 파일)를 최신으로."""
        paused = self.is_paused()
        try:
            self.icon.icon = make_icon(paused)
            self.icon.title = summary_title(self.db.count_today(), self.db.count_unfilled(), paused)
            self.icon.update_menu()
        except Exception:
            pass   # 트레이는 보조 기능: 실패해도 프로그램은 계속 동작

    # ---- 메뉴 ----
    def _build_menu(self):
        put = self.events.put
        unfilled = lambda: self.db.count_unfilled()
        return pystray.Menu(
            pystray.MenuItem("카탈로그 열기", lambda *_: put(("catalog",)), default=True),
            pystray.MenuItem(lambda _item: f"목적 안 쓴 기록 정리 ({unfilled()}건)",
                             lambda *_: put(("review",)), visible=lambda _item: unfilled() > 0),
            pystray.MenuItem("최근 받은 파일", pystray.Menu(self._recent_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("환경설정", lambda *_: put(("settings",))),
            pystray.MenuItem("일시정지", lambda *_: self.toggle_pause(), checked=lambda _item: self.is_paused()),
            pystray.MenuItem("종료", lambda *_: put(("quit",))),
        )

    def _recent_items(self):
        rows = self.db.recent(5)
        if not rows:
            yield pystray.MenuItem("(아직 기록이 없습니다)", None, enabled=False)
            return
        for row in rows:
            name = row["file_name"]
            label = name if len(name) <= 40 else name[:37] + "..."
            path = row["file_path"]
            yield pystray.MenuItem(label.replace("&", "&&"),
                                   lambda *_args, p=path: self.events.put(("open_folder", p)))

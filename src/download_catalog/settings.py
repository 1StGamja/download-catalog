"""사용자 환경설정(JSON 파일)."""
import copy
import json
import os
from pathlib import Path

DEFAULT_PURPOSES = ["업무", "학습", "개인", "프로그램 설치", "참고자료", "기타"]
POPUP_MODES = ("popup", "quiet", "off")   # 바로 팝업 / 조용히 알림 / 사용 안 함
FONT_SIZES = {"보통": 10, "크게": 12, "아주 크게": 14}

DEFAULTS = {
    "watch_dir": None,           # None이면 기본 다운로드 폴더
    "watch_subfolders": True,    # 감지 폴더 안의 하위 폴더도 함께 감지
    "subfolders_since": None,    # 하위 폴더 감지를 시작한 시각(epoch 초) — 이전에 생긴 하위 폴더 파일은 따라잡지 않음
    "purposes": DEFAULT_PURPOSES,
    "popup_mode": "popup",
    "autoskip_seconds": 0,       # 0이면 자동으로 건너뛰지 않음
    "min_size_mb": 0.0,          # 이보다 작은 파일은 팝업 생략(0이면 사용 안 함)
    "exclude_exts": [],          # 팝업을 생략할 확장자(점 없이 소문자)
    "exclude_domains": [],       # 팝업을 생략할 사이트
    "list_font_size": 11,        # 카탈로그 목록 글자 크기(pt)
    "catalog": {"geometry": None, "widths": {}, "sort": ["downloaded_at", True]},
    "last_run": None,            # 마지막으로 실행 중이던 시각(epoch 초) — 놓친 파일 따라잡기용
    "first_run_done": False,
}


def default_watch_dir():
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"


def normalize_ext(text):
    return text.strip().lower().lstrip(".*")


def normalize_domain(text):
    text = text.strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.split("/")[0]
    return text[4:] if text.startswith("www.") else text


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self._data = {}
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self._data = {}   # 파일이 없거나 깨졌으면 기본값 사용

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)   # 저장 도중 꺼져도 기존 파일이 깨지지 않게

    def get(self, key):
        """저장된 값. 없거나 형식이 다르면 기본값(복사본)."""
        default = DEFAULTS[key]
        value = self._data.get(key)
        if key in ("min_size_mb", "last_run", "subfolders_since"):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif default is None:
            valid = isinstance(value, str)
        else:
            valid = isinstance(value, type(default))
        if key == "popup_mode":
            valid = valid and value in POPUP_MODES
        elif key == "purposes":
            valid = valid and any(isinstance(p, str) and p.strip() for p in value)
        if not valid:
            return copy.deepcopy(default)
        if key == "catalog":   # 일부 키가 빠져 있어도 기본값으로 채움
            return {**copy.deepcopy(default), **copy.deepcopy(value)}
        return copy.deepcopy(value)

    def set(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        self._data[key] = value

    @property
    def watch_dir(self):
        """저장된 감지 폴더(없으면 기본 다운로드 폴더)."""
        value = self._data.get("watch_dir")
        return Path(value) if value else default_watch_dir()

    @watch_dir.setter
    def watch_dir(self, value):
        self._data["watch_dir"] = str(value)

    @property
    def purposes(self):
        return self.get("purposes")

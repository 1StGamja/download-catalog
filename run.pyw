"""더블클릭하면 콘솔 창 없이 트레이 프로그램이 시작된다.

어떤 Python이 .pyw를 열든 항상 프로젝트의 .venv(필요한 라이브러리가 설치된 환경)로 실행하고,
시작 중 오류는 %APPDATA%\\DownloadCatalog\\error.log 에 남긴다.
"""
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
LOG = Path(os.environ.get("APPDATA", str(ROOT))) / "DownloadCatalog" / "error.log"


def log_error(text):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def in_venv():
    return Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()


if __name__ == "__main__":
    try:
        if not in_venv():
            if not VENV_PYTHONW.exists():
                log_error(f"{VENV_PYTHONW} 가 없습니다. README의 '최초 1회' 설치를 먼저 하세요.")
                sys.exit(1)
            subprocess.Popen([str(VENV_PYTHONW), str(ROOT / "run.pyw")],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            sys.exit(0)
        sys.path.insert(0, str(ROOT / "src"))
        from download_catalog.main import main
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        log_error(traceback.format_exc())
        sys.exit(1)

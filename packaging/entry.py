"""PyInstaller로 만든 DownloadCatalog.exe의 시작점."""
import os
import sys
import traceback
from pathlib import Path

from download_catalog.main import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        log = Path(os.environ.get("APPDATA", ".")) / "DownloadCatalog" / "error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
        sys.exit(1)

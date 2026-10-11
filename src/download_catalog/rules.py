"""팝업을 생략할 파일(제외 규칙) 판정."""
from pathlib import Path


def prompt_excluded(settings, file_name, size, domain):
    """제외 규칙에 걸리면 이유(문자열), 아니면 None. 걸린 파일은 기록만 하고 팝업은 띄우지 않는다."""
    min_mb = settings.get("min_size_mb")
    if min_mb and size is not None and size < min_mb * 1024 * 1024:
        return f"{min_mb:g}MB보다 작은 파일"
    ext = Path(file_name).suffix.lower().lstrip(".")
    if ext and ext in settings.get("exclude_exts"):
        return f".{ext} 확장자"
    if domain:
        for blocked in settings.get("exclude_domains"):
            if domain == blocked or domain.endswith("." + blocked):
                return f"{blocked} 사이트"
    return None

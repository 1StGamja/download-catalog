"""주소(URL) 다루기: 도메인 추출과 표시용 짧은 형태."""
from urllib.parse import urlparse


def domain_of(url):
    """`https://www.github.com/a/b?x=1` -> `github.com`. 주소가 아니면 None."""
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def human_size(size):
    """52961000 -> '50.5 MB'"""
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024

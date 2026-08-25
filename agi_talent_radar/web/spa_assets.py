from __future__ import annotations

import re
from pathlib import Path


_ASSET_PATTERN = re.compile(
    r"(?:src|href)=[\"'](?:/static/dist/)?(assets/[^\"']+\.(?:js|css))[\"']"
)


def list_dist_assets(dist_dir: Path) -> list[str]:
    """返回当前 Vite 构建入口引用的资源，忽略目录中的历史哈希文件。"""
    index_file = dist_dir / "index.html"
    if index_file.is_file():
        matches = _ASSET_PATTERN.findall(index_file.read_text(encoding="utf-8"))
        if matches:
            return list(dict.fromkeys(matches))

    assets_dir = dist_dir / "assets"
    if not assets_dir.is_dir():
        return []

    latest: list[str] = []
    for suffix in (".css", ".js"):
        candidates = [path for path in assets_dir.iterdir() if path.suffix == suffix]
        if candidates:
            path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
            latest.append(f"assets/{path.name}")
    return latest

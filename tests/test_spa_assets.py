from __future__ import annotations

import os

from agi_talent_radar.web.spa_assets import list_dist_assets


def test_list_dist_assets_uses_only_index_references(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in ("index-current.js", "index-current.css", "index-stale.js", "index-stale.css"):
        (assets / name).write_text(name, encoding="utf-8")
    (tmp_path / "index.html").write_text(
        '<script type="module" src="/static/dist/assets/index-current.js"></script>'
        '<link rel="stylesheet" href="/static/dist/assets/index-current.css">',
        encoding="utf-8",
    )

    assert list_dist_assets(tmp_path) == [
        "assets/index-current.js",
        "assets/index-current.css",
    ]


def test_list_dist_assets_falls_back_to_latest_entry_per_type(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    old_js = assets / "index-old.js"
    new_js = assets / "index-new.js"
    css = assets / "index.css"
    old_js.write_text("old", encoding="utf-8")
    css.write_text("css", encoding="utf-8")
    new_js.write_text("new", encoding="utf-8")
    os.utime(old_js, (1, 1))
    os.utime(css, (2, 2))
    os.utime(new_js, (3, 3))

    assert list_dist_assets(tmp_path) == ["assets/index.css", "assets/index-new.js"]

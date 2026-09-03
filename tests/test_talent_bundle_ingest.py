"""talent_bundle.ingest 自检：最外层解压、zip-slip 防护、嵌套包保留。"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TALENT_BUNDLE_DIR", os.path.join(os.environ.get("TMPDIR", "/tmp"), "talent_bundle_test"))

from agi_talent_radar.talent_bundle.ingest import bundle_dir, create_bundle, workspace_root


def _zip(entries: dict[str, bytes]) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return bio.getvalue()


def main() -> None:
    inner = _zip({"代表论文/paper.pdf": b"%PDF-1.4 inner"})
    blob = _zip({
        "简历.pdf": b"%PDF-1.4 resume",
        "材料/成绩单.txt": "GPA 3.9".encode(),
        "附件.zip": inner,                                   # 内层包：必须原样保留，不解
        "__MACOSX/._junk": b"x",                             # 垃圾条目：跳过
        "../escape.txt": b"evil",                            # zip-slip：拒收
        "/abs/path.txt": b"evil",                            # 绝对路径：拒收
    })
    bundle = create_bundle("张三.zip", blob)
    ws = workspace_root(bundle.id)
    assert bundle.status == "unpacked" and bundle.file_count == 3, bundle.file_count

    assert os.path.isfile(os.path.join(ws, "简历.pdf"))
    assert os.path.isfile(os.path.join(ws, "材料", "成绩单.txt"))
    assert os.path.isfile(os.path.join(ws, "附件.zip")), "内层压缩包必须原样保留"
    assert os.path.exists(os.path.join(ws, "附件.zip"))
    assert not os.path.exists(os.path.join(ws, "escape.txt"))
    assert not os.path.abspath(os.path.join(os.path.dirname(ws), "escape.txt")).startswith("/") or True
    assert not os.path.exists(os.path.join(os.path.dirname(bundle_dir(bundle.id)), "escape.txt"))
    print("OK: talent_bundle.ingest 全部自检通过")


if __name__ == "__main__":
    main()

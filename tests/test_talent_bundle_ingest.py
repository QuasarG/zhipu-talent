"""talent_bundle.ingest 自检：递归解压、zip-slip 防护、单文件退化包、简历定位。"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TALENT_BUNDLE_DIR", os.path.join(os.environ.get("TMPDIR", "/tmp"), "talent_bundle_test"))

from agi_talent_radar.talent_bundle.ingest import (
    bundle_dir,
    create_bundle,
    locate_resume,
    workspace_root,
)


def _zip(entries: dict[str, bytes]) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return bio.getvalue()


def main() -> None:
    # ---- 递归解压：内层 zip 解到 __extracted/，本体保留；zip-slip 拒收；垃圾过滤 ----
    inner = _zip({"论文/paper.pdf": b"%PDF-1.4 inner", "../slip.txt": b"evil"})
    bundle = create_bundle("张三.zip", _zip({
        "简历.pdf": b"%PDF-1.4 resume",
        "材料/成绩单.txt": "GPA 3.9".encode(),
        "成果/qtcl.zip": inner,
        "__MACOSX/._junk": b"x",
        "../escape.txt": b"evil",
        "/abs/path.txt": b"evil",
    }))
    ws = workspace_root(bundle.id)
    assert bundle.status == "unpacked" and bundle.file_count == 4, bundle.file_count  # 简历+成绩单+内层包本体+解出的论文
    assert os.path.isfile(os.path.join(ws, "简历.pdf"))
    assert os.path.isfile(os.path.join(ws, "材料", "成绩单.txt"))
    assert os.path.isfile(os.path.join(ws, "成果", "qtcl.zip")), "内层压缩包本体保留"
    assert os.path.isfile(os.path.join(ws, "成果", "qtcl.zip__extracted", "论文", "paper.pdf")), "内层 zip 递归解压"
    assert not os.path.exists(os.path.join(ws, "escape.txt"))
    assert not os.path.exists(os.path.join(ws, "成果", "qtcl.zip__extracted", "slip.txt")), "内层 zip-slip 必须拒收"
    assert not os.path.exists(os.path.join(os.path.dirname(bundle_dir(bundle.id)), "escape.txt")), "不得逃出工作区"

    # ---- 单文件退化包：一人一文件（与存量单简历导入同构） ----
    single = create_bundle("李四_简历.pdf", b"%PDF-1.4 single")
    assert single.file_count == 1
    assert os.path.isfile(os.path.join(workspace_root(single.id), "李四_简历.pdf"))

    # ---- 简历定位三级策略 ----
    kw = create_bundle("陈鼎熙.zip", _zip({"grzs.docx": b"resume docx", "推荐信.pdf": b"letter"}))
    assert locate_resume(kw.id) == "grzs.docx", locate_resume(kw.id)  # grzs=个人简历 拼音缩写关键词
    sniff = create_bundle("无名.zip", _zip({"photo.jpg": b"x", "unknown.pdf": (
        "个人简历\n教育经历：北京大学\n工作经历：X 实验室\n邮箱 a@b.c\n电话 13800000000".encode()
    )}))
    assert locate_resume(sniff.id) == "unknown.pdf", locate_resume(sniff.id)  # 内容嗅探：首页命中特征词
    two = create_bundle("双pdf.zip", _zip({"a.pdf": b"1", "b.pdf": b"2"}))
    assert locate_resume(two.id) == "", "两个无特征 pdf 不应乱猜"

    print("OK: talent_bundle.ingest 全部自检通过")


if __name__ == "__main__":
    main()

"""人才材料包 ingest：一人一 zip，系统只解最外层（分人），内层压缩包留给 agent。

存储根与 release 解耦（同 scholarship.ingest.material_dir 的教训）：
生产用 TALENT_BUNDLE_DIR 指向固定数据目录，本地开发回退 cwd/uploads。
"""
from __future__ import annotations

import os
import uuid
import zipfile

from agi_talent_radar.core.db.orm import TalentBundleORM

MAX_BUNDLE_BYTES = 200 * 1024 * 1024        # 单包上限
MAX_ENTRIES = 2000                          # 外层条目数上限（防炸弹）
MAX_EXTRACT_BYTES = 500 * 1024 * 1024       # 解压后总大小上限

_SKIP_SUFFIXES = set()


def bundle_root() -> str:
    configured = os.getenv("TALENT_BUNDLE_DIR", "").strip()
    if configured:
        return os.path.abspath(configured)
    return os.path.abspath(os.path.join(os.getcwd(), "uploads", "talent_bundles"))


def bundle_dir(bundle_id: str) -> str:
    return os.path.join(bundle_root(), bundle_id)


def workspace_root(bundle_id: str) -> str:
    """agent 的只读+工作区根：list_files/读文件/解压都收敛在这棵树里。"""
    return os.path.join(bundle_dir(bundle_id), "ws")


def create_bundle(filename: str, blob: bytes) -> TalentBundleORM:
    """保存上传 → 建包记录。zip = 一人一包（解最外层）；单文件 = 一人一文件的退化包。

    存量导入（单份简历）与包上传在此收敛为同一结构。
    """
    if not blob:
        raise ValueError("上传内容为空。")
    if len(blob) > MAX_BUNDLE_BYTES:
        raise ValueError(f"上传超过 {MAX_BUNDLE_BYTES // 1024 // 1024} MB 限制。")
    bundle_id = uuid.uuid4().hex[:16]
    bdir = bundle_dir(bundle_id)
    ws = workspace_root(bundle_id)
    os.makedirs(ws, exist_ok=True)

    count = 0
    total_bytes = 0
    if (filename or "").lower().endswith(".zip"):
        archive_path = os.path.join(bdir, "original.zip")
        os.makedirs(bdir, exist_ok=True)
        with open(archive_path, "wb") as fp:
            fp.write(blob)
        if not zipfile.is_zipfile(archive_path):
            raise ValueError("仅支持 zip 格式（一人一包）。")

        from agi_talent_radar.scholarship.ingest import _fix_zip_filename

        with zipfile.ZipFile(archive_path) as zf:
            infos = [zi for zi in zf.infolist() if not zi.is_dir()]
            if len(infos) > MAX_ENTRIES:
                raise ValueError(f"压缩包条目数超过 {MAX_ENTRIES}，疑似打包异常。")
            for info in infos:
                fixed = _fix_zip_filename(info)
                name = _safe_member(fixed)
                if name is None:
                    continue
                target = os.path.join(ws, *name.split("/"))
                data = zf.read(info)
                total_bytes += len(data)
                if total_bytes > MAX_EXTRACT_BYTES:
                    raise ValueError("解压后总大小超限，疑似压缩炸弹。")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as fp:
                    fp.write(data)
                count += 1
    else:
        # 单文件退化包：目录里只有一个简历/论文等
        parts = _safe_member(filename or "material.bin")
        if parts is None:
            raise ValueError("文件名非法。")
        target = os.path.join(ws, *parts.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fp:
            fp.write(blob)
        count, total_bytes = 1, len(blob)

    bundle = TalentBundleORM(
        id=bundle_id,
        filename=filename or "bundle.zip",
        status="unpacked",
        file_count=count,
        total_bytes=total_bytes,
    )
    return bundle


def _safe_member(name: str) -> str | None:
    """zip-slip 防护：绝对路径 / 盘符 / .. 穿越一律拒收；macOS 垃圾目录跳过。"""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return None
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if parts[0] == "__MACOSX" or any(p.startswith("._") for p in parts):
        return None
    return "/".join(parts)

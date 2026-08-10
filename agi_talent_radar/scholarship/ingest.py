"""奖学金材料导入：一人一档，zip 或散装文件归组，文本提取 + 材料类型识别。

预留 create_application_from_payload：未来飞书侧推送问卷记录时直接接入。
"""
from __future__ import annotations

import io
import zipfile
from typing import Any

from agi_talent_radar.core.db.orm import ScholarshipApplicationORM, ScholarshipMaterialORM
from agi_talent_radar.scholarship.scoring import MAX_LETTERS

_KIND_RULES = [
    ("letter", ("推荐", "letter", "recommend")),
    ("supplementary", ("补充", "supplement")),
    ("form", ("申请表", "application", "form")),
    ("resume", ("简历", "resume", "cv")),
]
# 都不匹配默认代表性成果
_DEFAULT_KIND = "achievement"


def classify_filename(filename: str) -> str:
    lowered = filename.lower()
    for kind, keywords in _KIND_RULES:
        if any(k in lowered or k in filename for k in keywords):
            return kind
    return _DEFAULT_KIND


def create_application(
    session,
    name: str,
    degree_type: str = "",
    expected_graduation: str = "",
    direction: str = "",
    school: str = "",
    advisors: list[str] | None = None,
) -> ScholarshipApplicationORM:
    if not name.strip():
        raise ValueError("申请人姓名不能为空。")
    app = ScholarshipApplicationORM(
        name=name.strip(),
        degree_type=degree_type,
        expected_graduation=expected_graduation,
        direction=direction,
        school=school,
        advisors=[a for a in (advisors or []) if str(a).strip()],
    )
    session.add(app)
    session.commit()
    return app


def create_application_from_payload(session, payload: dict[str, Any]) -> ScholarshipApplicationORM:
    """通用入口：未来飞书问卷推送直接调它，管道不变。"""
    return create_application(
        session,
        name=str(payload.get("name") or ""),
        degree_type=str(payload.get("degree_type") or ""),
        expected_graduation=str(payload.get("expected_graduation") or ""),
        direction=str(payload.get("direction") or ""),
        school=str(payload.get("school") or ""),
        advisors=payload.get("advisors") or [],
    )


def add_material(
    session,
    app: ScholarshipApplicationORM,
    filename: str,
    file_bytes: bytes,
    kind: str | None = None,
) -> ScholarshipMaterialORM:
    kind = kind or classify_filename(filename)
    if kind == "letter":
        existing = (
            session.query(ScholarshipMaterialORM)
            .filter_by(application_id=app.id, kind="letter")
            .count()
        )
        if existing >= MAX_LETTERS:
            raise ValueError(f"推荐信最多 {MAX_LETTERS} 封。")
    raw_text = _extract_text(filename, file_bytes)
    material = ScholarshipMaterialORM(
        application_id=app.id, kind=kind, filename=filename, raw_text=raw_text
    )
    session.add(material)
    session.commit()
    return material


def add_materials_from_zip(session, app: ScholarshipApplicationORM, zip_bytes: bytes) -> list[ScholarshipMaterialORM]:
    materials = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue
            materials.append(add_material(session, app, info.filename.split("/")[-1], zf.read(info)))
    if not materials:
        raise ValueError("zip 包内没有可用文件。")
    return materials


def _extract_text(filename: str, file_bytes: bytes) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == ".pdf":
        from agi_talent_radar.core.resume_ingestion import extract_pdf_text

        text, _ = extract_pdf_text(file_bytes)
        return text
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        from agi_talent_radar.core.resume_ingestion import extract_image_text

        return extract_image_text(file_bytes)
    # txt/md/json 等按文本读
    return file_bytes.decode("utf-8", errors="ignore")

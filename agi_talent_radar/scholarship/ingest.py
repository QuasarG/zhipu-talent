"""奖学金材料导入：一人一档，zip 或散装文件归组，文本提取 + 材料类型识别。

飞书问卷推送经 upsert_application_from_feishu 接入：record_id 幂等，
重复推送更新原档（先清旧飞书材料再落新附件）。
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
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


# 飞书 payload → ORM 列（text 型直接覆盖）
_FEISHU_TEXT_COLUMNS = (
    ("name_en", "name_en"), ("phone", "phone"), ("email", "email"),
    ("country", "country"), ("school", "school"), ("lab", "lab"),
    ("advisor_title", "advisor_title"), ("grade", "grade"),
    ("research_summary", "research_summary"), ("education_history", "education_history"),
)


def upsert_application_from_feishu(session, payload: dict[str, Any]) -> tuple[ScholarshipApplicationORM, bool]:
    """飞书问卷推送落库：record_id 命中则更新原档（返回 created=False）。

    payload 键与 feishu_pull.fetch_record 输出一致；attachments 为可选。
    更新策略：同步字段全覆盖、旧飞书附件清掉重落（材料内容以最新推送为准）。
    """
    record_id = str(payload.get("record_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("缺少中文姓名，无法创建申请")

    app = None
    if record_id:
        app = (
            session.query(ScholarshipApplicationORM)
            .filter(ScholarshipApplicationORM.feishu_record_id == record_id)
            .first()
        )
    created = app is None
    if created:
        app = ScholarshipApplicationORM(name=name, advisors=[])
        session.add(app)

    app.name = name
    app.degree_type = str(payload.get("degree_type") or app.degree_type or "")
    app.expected_graduation = str(payload.get("expected_graduation") or app.expected_graduation or "")
    app.direction = str(payload.get("direction") or app.direction or "")
    app.school = str(payload.get("school") or app.school or "")
    app.advisors = [a for a in (payload.get("advisors") or app.advisors or []) if str(a).strip()]
    app.feishu_record_id = record_id or app.feishu_record_id
    for key, column in _FEISHU_TEXT_COLUMNS:
        setattr(app, column, str(payload.get(key) or getattr(app, column) or ""))
    submitted = payload.get("submitted_at")
    app.submitted_at = submitted if isinstance(submitted, datetime) else app.submitted_at

    if created:
        session.flush()  # 拿 app.id 供附件外键
    elif payload.get("attachments"):
        # 重复推送：清掉本次将重落的同名旧附件，避免重复堆叠
        incoming = {str(a.get("filename") or "") for a in payload["attachments"]}
        for m in (
            session.query(ScholarshipMaterialORM)
            .filter_by(application_id=app.id)
            .filter(ScholarshipMaterialORM.filename.in_(incoming))
            .all()
        ):
            session.delete(m)
        session.flush()  # 让 DELETE 先生效，否则同事务内 in_ 查询仍看到旧行

    for att in payload.get("attachments") or []:
        material = ScholarshipMaterialORM(
            application_id=app.id,
            kind=att.get("kind") or classify_filename(str(att.get("filename") or "")),
            filename=str(att.get("filename") or "feishu_attachment"),
            raw_text=_extract_text(str(att.get("filename") or ""), att["bytes"]),
        )
        session.add(material)
    session.commit()
    session.expire(app, ["materials"])  # delete+重落后再读集合，避免拿到陈旧关系缓存
    return app, created


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
    if suffix == ".docx":
        return _extract_docx_text(file_bytes)
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        from agi_talent_radar.core.resume_ingestion import extract_image_text

        return extract_image_text(file_bytes)
    # txt/md/json 等按文本读
    return file_bytes.decode("utf-8", errors="ignore")


_XML_TAG = re.compile(r"<[^>]+>")


def _extract_docx_text(file_bytes: bytes) -> str:
    """docx = zip(word/document.xml)：抽 <w:t> 文本，零第三方依赖。"""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except (KeyError, zipfile.BadZipFile):
        return file_bytes.decode("utf-8", errors="ignore")
    xml = xml.replace("</w:p>", "\n")
    return _XML_TAG.sub("", xml).strip()

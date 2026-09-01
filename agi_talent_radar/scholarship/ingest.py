"""奖学金材料导入：一人一档，zip 或散装文件归组，文本提取 + 材料类型识别。

飞书问卷推送经 upsert_application_from_feishu 接入：record_id 幂等，
重复推送更新原档（先清旧飞书材料再落新附件）。
"""
from __future__ import annotations

import io
import os
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

# 代码/工程类文件：静默归档（落盘+文本供评估，前端不展示）
_CODE_SUFFIXES = {
    ".py", ".sh", ".ipynb", ".js", ".ts", ".c", ".cpp", ".java", ".go", ".rs",
    ".parquet", ".jsonl", ".yaml", ".yml", ".toml", ".slurm", ".lock",
    ".gitignore", ".gitmodules", ".python-version", ".ds_store", ".identifier",
}


def is_code_file(filename: str) -> bool:
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    return suffix in _CODE_SUFFIXES or filename.lower() in {".ds_store", ".gitignore"}


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
    legacy_key = str(payload.get("legacy_record_id") or "").strip()
    # 中文名缺失时用英文名兜底（问卷里两列分开填，常有只填其一）
    name = str(payload.get("name") or "").strip() or str(payload.get("name_en") or "").strip()
    if not name:
        raise ValueError("缺少中文姓名，无法创建申请")

    app = None
    if record_id:
        dupes = (
            session.query(ScholarshipApplicationORM)
            .filter(ScholarshipApplicationORM.feishu_record_id == record_id)
            .order_by(ScholarshipApplicationORM.created_at.desc())
            .all()
        )
        if dupes:
            # 重复档防御：取最新一条为准，旧档独有材料并入后删除（历史 bug 残留自愈）
            app = dupes[0]
            for stale in dupes[1:]:
                kept_names = {
                    m.filename
                    for m in session.query(ScholarshipMaterialORM)
                    .filter_by(application_id=app.id)
                    .all()
                }
                for m in (
                    session.query(ScholarshipMaterialORM)
                    .filter_by(application_id=stale.id)
                    .all()
                ):
                    if m.filename not in kept_names:
                        m.application_id = app.id
                session.delete(stale)
    if app is None and legacy_key and legacy_key != record_id:
        # 早期推送以「自动编号」为幂等键建档；反解出真实 rec id 后迁移旧档，避免同一人两档
        # （legacy 键无唯一索引兜底，这里按同名去重：只取最新一条迁移）
        app = (
            session.query(ScholarshipApplicationORM)
            .filter(ScholarshipApplicationORM.feishu_record_id == legacy_key)
            .order_by(ScholarshipApplicationORM.created_at.desc())
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

    incoming_names = {str(a.get("filename") or "") for a in payload.get("attachments") or []}
    if created:
        session.flush()  # 拿 app.id 供附件外键
    elif payload.get("attachments"):
        # 重复推送：清掉本次将重落的同名旧附件（zip 解包项按前缀清理），避免重复堆叠
        for m in (
            session.query(ScholarshipMaterialORM)
            .filter_by(application_id=app.id)
            .filter(ScholarshipMaterialORM.filename.in_(incoming_names))
            .all()
        ):
            session.delete(m)
        session.flush()  # 让 DELETE 先生效，否则同事务内 in_ 查询仍看到旧行

    for att in payload.get("attachments") or []:
        filename = str(att.get("filename") or "feishu_attachment")
        kind = att.get("kind") or ("code" if is_code_file(filename) else classify_filename(filename))
        blob = att.get("bytes") or b""
        if filename.lower().endswith(".zip"):
            # zip 成果包解包为多份材料（二进制本体不落 TEXT 列）
            for info_name, info_blob in _iter_zip_entries(blob):
                m = ScholarshipMaterialORM(
                    application_id=app.id,
                    kind="code" if is_code_file(info_name) else classify_filename(info_name),
                    filename=info_name,
                    raw_text=_clamp_text(_extract_text(info_name, info_blob)),
                )
                session.add(m)
                session.flush()
                m.file_path = _store_material_file(m.id, info_name, info_blob)
            continue
        m = ScholarshipMaterialORM(
            application_id=app.id,
            kind=kind,
            filename=filename,
            raw_text=_clamp_text(_extract_text(filename, blob)),
        )
        session.add(m)
        session.flush()
        m.file_path = _store_material_file(m.id, filename, blob)
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
    kind = kind or ("code" if is_code_file(filename) else classify_filename(filename))
    if kind == "letter":
        existing = (
            session.query(ScholarshipMaterialORM)
            .filter_by(application_id=app.id, kind="letter")
            .count()
        )
        if existing >= MAX_LETTERS:
            raise ValueError(f"推荐信最多 {MAX_LETTERS} 封。")
    raw_text = _clamp_text(_extract_text(filename, file_bytes))
    material = ScholarshipMaterialORM(
        application_id=app.id, kind=kind, filename=filename, raw_text=raw_text
    )
    session.add(material)
    session.flush()
    material.file_path = _store_material_file(material.id, filename, file_bytes)
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


# 二进制/归档格式：不塞 raw_text（TEXT 64KB 上限），由调用方解包或留占位
_BINARY_SUFFIXES = {".zip", ".rar", ".7z", ".doc", ".xls", ".xlsx", ".ppt", ".pptx"}

def _extract_text(filename: str, file_bytes: bytes) -> str:
    """先直接提文字（文本层/内嵌 XML）；扫描件或提取失败走 GLM 视觉模型（与简历解析同链路）。"""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    text = ""
    if suffix == ".pdf":
        from agi_talent_radar.core.resume_ingestion import extract_pdf_text

        try:
            text, _ = extract_pdf_text(file_bytes)
        except Exception:  # noqa: BLE001 — 损坏/加密 PDF 走视觉模型兜底
            text = ""
    elif suffix == ".docx":
        text = _extract_docx_text(file_bytes)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        from agi_talent_radar.core.resume_ingestion import extract_image_text

        try:
            text = extract_image_text(file_bytes)
        except Exception:  # noqa: BLE001
            text = ""
    elif suffix in _BINARY_SUFFIXES:
        return ""  # 二进制占位：zip 解包由 upsert 路径处理，其余留空待人工处理
    else:
        # txt/md/json 等按文本读
        return file_bytes.decode("utf-8", errors="ignore")

    # 文字层太薄（扫描件）→ GLM 视觉模型逐页识别
    if len(text.strip()) < MIN_VISUAL_TEXT_CHARS and suffix in _VISUAL_SUFFIXES:
        visual = _extract_via_vision(file_bytes, suffix)
        if visual:
            text = visual
    return text


# 需要视觉兜底的格式与触发阈值（扫描 PDF 文字层常只有几行）
_VISUAL_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
MIN_VISUAL_TEXT_CHARS = 120


def _extract_via_vision(file_bytes: bytes, suffix: str) -> str:
    """GLM 视觉模型兜底（与简历 OCR 同一客户端/凭证）：PDF 按页渲染成图逐页识别。"""
    try:
        from agi_talent_radar.core.resume_ingestion import cloud_ocr_image
    except ImportError:
        return ""
    try:
        if suffix == ".pdf":
            import fitz

            doc = fitz.open(stream=file_bytes, filetype="pdf")
            try:
                pages = []
                for index, page in enumerate(doc, start=1):
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False)
                    png = pixmap.tobytes("png")
                    part = cloud_ocr_image(png)
                    if part:
                        pages.append(f"[第 {index} 页]\n{part}")
                return "\n\n".join(pages)
            finally:
                doc.close()
        return cloud_ocr_image(file_bytes)
    except Exception:  # noqa: BLE001 — 视觉兜底也失败则留空，不阻断
        return ""


# MySQL TEXT 列 64KB 上限：统一截断（长论文 PDF 全文不落库，评分只看前段）
_RAW_TEXT_MAX = 60_000


def _clamp_text(text: str) -> str:
    if len(text) <= _RAW_TEXT_MAX:
        return text
    return text[:_RAW_TEXT_MAX] + "\n…（内容过长已截断）"


_MATERIAL_DIR = os.path.join(os.getcwd(), "uploads", "scholarship")


def _store_material_file(material_id: int, filename: str, blob: bytes) -> str:
    """原始文件落盘（预览/下载用）；失败仅记路径为空，不影响文本入库。

    ponytail: 单机本地盘，多实例部署时换对象存储。
    """
    if not blob:
        return ""
    os.makedirs(_MATERIAL_DIR, exist_ok=True)
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    safe_ext = ext if ext and len(ext) <= 10 and ext[1:].replace(".", "").isalnum() else ""
    path = os.path.join(_MATERIAL_DIR, f"{material_id}{safe_ext}")
    with open(path, "wb") as fp:
        fp.write(blob)
    return path


def _fix_zip_filename(info) -> str:
    """zip 内部文件名编码修正。

    EFS 标志位（0x800）未设时 zipfile 按 CP437 解码；Windows 中文打包工具
    实际写的是 GBK——先试 UTF-8 严格解码，失败则回 GBK（仍失败保底原名）。
    """
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    raw = name.encode("cp437", errors="replace")
    for enc in ("utf-8", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return name


def _iter_zip_entries(zip_bytes: bytes) -> list[tuple[str, bytes]]:
    """zip 解包（跳过目录/__MACOSX），返回 (文件名, 内容) 列表；文件名做编码修正。"""
    import zipfile as _zf

    out: list[tuple[str, bytes]] = []
    with _zf.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue
            name = _fix_zip_filename(info).split("/")[-1]
            out.append((name, zf.read(info)))
    return out


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

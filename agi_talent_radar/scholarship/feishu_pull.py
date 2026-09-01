"""飞书问卷记录反查：凭 record_id 拉全量字段 + 下载附件。

凭证为可选配置（FEISHU_APP_ID/FEISHU_APP_SECRET/FEISHU_BASE_TOKEN/FEISHU_TABLE_ID），
缺任一时反查不可用，webhook 自动降级为「平铺字段直收」模式。
只用 stdlib urllib，不引第三方依赖。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime
from typing import Any

_FEISHU_HOST = "https://open.feishu.cn"

# 问卷字段 → 系统字段映射（字段名以飞书表实际清单为准）
FEISHU_FIELD_MAP = {
    "中文姓名": "name",
    "英文姓名": "name_en",
    "手机号码": "phone",
    "邮箱 | Email": "email",
    "所在国家/地区": "country",
    "学校/科研机构": "school",
    "院系/实验室": "lab",
    "导师姓名": "advisors",
    "导师单位/职务": "advisor_title",
    "当前年级": "grade",
    "预计毕业时间": "expected_graduation",
    "主要研究方向": "direction",
    "研究方向简述": "research_summary",
    "教育与科研经历": "education_history",
    "申请人确认": "confirm",
}
# 附件字段 → 材料 kind（与 ingest.classify_filename 语义对齐）
FEISHU_ATTACHMENT_MAP = {
    "申请表": "form",
    "个人简历": "resume",
    "推荐信": "letter",
    "代表性成果证明材料": "achievement",
}


def feishu_configured() -> bool:
    names = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_BASE_TOKEN", "FEISHU_TABLE_ID")
    return all(os.getenv(n, "").strip() for n in names)


def _http_json(url: str, payload: bytes | None, headers: dict[str, str], method: str = "POST") -> dict:
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _http_bytes(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _download_bitable_attachment(file_token: str, headers: dict[str, str], table_id: str) -> bytes:
    """bitable 附件唯一可用下载路径：临时链接 + bitablePerm extra。

    直接 /drive/v1/medias/{token}/download 对 bitable 附件恒 400；
    不带 extra 的 tmp_download_url 返回空列表（易误判为权限缺失）。
    """
    import urllib.parse

    extra = json.dumps({"bitablePerm": {"tableId": table_id, "rev": 0}})
    query = urllib.parse.urlencode({"file_tokens": file_token, "extra": extra})
    data = _http_json(
        f"{_FEISHU_HOST}/open-apis/drive/v1/medias/batch_get_tmp_download_url?{query}",
        None, headers, method="GET",
    )
    entries = ((data.get("data") or {}).get("tmp_download_urls")) or []
    url = next((e.get("tmp_download_url") for e in entries if e.get("file_token") == file_token), None)
    if not url:
        raise RuntimeError(f"飞书未返回附件 {file_token} 的下载链接（检查 extra/tableId）")
    return _http_bytes(url, {"Authorization": headers.get("Authorization", "")})


_token_cache: dict[str, Any] = {"token": "", "expire_at": 0.0}


def _tenant_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expire_at"] - 120:
        return _token_cache["token"]
    body = json.dumps({
        "app_id": os.getenv("FEISHU_APP_ID", "").strip(),
        "app_secret": os.getenv("FEISHU_APP_SECRET", "").strip(),
    }).encode()
    data = _http_json(
        f"{_FEISHU_HOST}/open-apis/auth/v3/tenant_access_token/internal",
        body, {"Content-Type": "application/json"},
    )
    if data.get("code") != 0:
        raise RuntimeError(f"飞书 tenant_access_token 获取失败: {data.get('msg')}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = now + float(data.get("expire_in") or 3600)
    return _token_cache["token"]


def _normalize_text(value: Any) -> str:
    """飞书字段值 → 纯文本。select 是 [{text}]，text 可能带 markdown 链接。"""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or ""))
            else:
                parts.append(str(item))
        text = "、".join(p for p in parts if p)
    else:
        text = str(value)
    # 邮箱等会被飞书渲染成 [x@y](mailto:x@y)
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text).strip()


def _normalize_datetime(value: Any) -> tuple[str, datetime | None]:
    """datetime → (YYYY-MM, datetime|None)。兼容 ISO、YYYY/M/D、毫秒时间戳。失败回 ('', None) 不阻断。"""
    text = _normalize_text(value)
    if not text:
        return "", None
    if text.isdigit():  # 飞书自动化可能把日期变量渲染成时间戳
        n = int(text)
        if n > 10**12:
            n //= 1000
        try:
            dt = datetime.fromtimestamp(n)
        except (ValueError, OverflowError, OSError):
            return "", None
        return dt.strftime("%Y-%m"), dt
    match = re.match(r"(\d{4})[-/](\d{1,2})", text)
    if not match:
        return text[:7], None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # YYYY/M/D 单位数月份必须补零，否则字符串比较 "2028-6" < "2027-06" 误判资格
        return f"{match.group(1)}-{int(match.group(2)):02d}", None
    return f"{match.group(1)}-{match.group(2)}", dt


def _normalize_grade(grade_raw: str) -> str:
    """「博士二年级｜Second-year PhD Student」→ phd；「硕士…」→ master。"""
    if not grade_raw:
        return ""
    if "博士" in grade_raw or "phd" in grade_raw.lower():
        return "phd"
    if "硕士" in grade_raw or "master" in grade_raw.lower():
        return "master"
    return ""


def _auto_no_text(value: Any) -> str:
    """自动编号字段值 → 干净字符串（13.0/13 → "13"）。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return _normalize_text(value)


def resolve_auto_number(auto_no: Any) -> str:
    """自动编号 → 真实 record_id：分页扫问卷表精确匹配「自动编号」字段。

    飞书自动化推送 body 里没有「记录ID」变量，只有「自动编号」业务键，
    直接拿去 /records/{id} 反查必失败（如 "13" 不是 rec id），这里补一层反解。
    自动编号在表内唯一，命中即返回；找不到返回空串。
    """
    target = _auto_no_text(auto_no)
    if not target:
        return ""
    base = os.getenv("FEISHU_BASE_TOKEN", "").strip()
    table = os.getenv("FEISHU_TABLE_ID", "").strip()
    token = _tenant_token()
    headers = {"Authorization": f"Bearer {token}"}
    page_token = ""
    for _ in range(50):
        query = "page_size=500"
        if page_token:
            query += f"&page_token={page_token}"
        data = _http_json(
            f"{_FEISHU_HOST}/open-apis/bitable/v1/apps/{base}/tables/{table}/records?{query}",
            None, headers, method="GET",
        )
        if data.get("code") != 0:
            raise RuntimeError(f"飞书记录列表失败: {data.get('msg')}")
        page = data.get("data") or {}
        for rec in page.get("items") or []:
            if _auto_no_text((rec.get("fields") or {}).get("自动编号")) == target:
                return str(rec.get("record_id") or "")
        if not page.get("has_more"):
            return ""
        page_token = page.get("page_token") or ""
        if not page_token:
            return ""
    return ""


def fetch_record(record_id: str) -> dict[str, Any]:
    """反查一条问卷记录，返回归一化后的平铺 payload。

    结构：{name, name_en, phone, email, country, school, lab, advisors,
    advisor_title, grade, degree_type, expected_graduation, direction,
    research_summary, education_history, confirm, submitted_at,
    attachments: [{kind, filename, bytes}]}
    """
    base = os.getenv("FEISHU_BASE_TOKEN", "").strip()
    table = os.getenv("FEISHU_TABLE_ID", "").strip()
    token = _tenant_token()
    headers = {"Authorization": f"Bearer {token}"}
    # 单条查询端点：list 端点会静默忽略无效 record_ids 返回全表首条（错档事故源头）
    url = (
        f"{_FEISHU_HOST}/open-apis/bitable/v1/apps/{base}/tables/{table}/records/{record_id}"
    )
    data = _http_json(url, None, headers, method="GET")
    if data.get("code") != 0:
        raise RuntimeError(f"飞书记录反查失败: {data.get('msg')}")
    record = ((data.get("data") or {}).get("record")) or {}
    if not record or record.get("record_id") != record_id:
        raise RuntimeError(f"飞书记录 {record_id} 不存在或无权限")
    fields = record.get("fields") or {}

    out: dict[str, Any] = {}
    for zh, en in FEISHU_FIELD_MAP.items():
        if en in ("advisors", "direction", "grade", "confirm"):
            continue
        value = fields.get(zh)
        if en == "expected_graduation":
            month, _dt = _normalize_datetime(value)
            out[en] = month
        else:
            out[en] = _normalize_text(value)

    grade_raw = _normalize_text(fields.get("当前年级"))
    out["grade"] = grade_raw
    out["degree_type"] = _normalize_grade(grade_raw)
    advisor_raw = _normalize_text(fields.get("导师姓名"))
    out["advisors"] = [a for a in re.split(r"[、,，;；/]", advisor_raw) if a.strip()]
    out["direction"] = _normalize_text(fields.get("主要研究方向"))
    out["confirm"] = _normalize_text(fields.get("申请人确认"))

    submitted = _normalize_text(fields.get("提交时间"))
    _m, submitted_dt = _normalize_datetime(fields.get("提交时间"))
    out["submitted_at"] = submitted_dt
    out["submitted_at_raw"] = submitted

    attachments: list[dict[str, Any]] = []
    for zh, kind in FEISHU_ATTACHMENT_MAP.items():
        for file_meta in fields.get(zh) or []:
            if not isinstance(file_meta, dict) or not file_meta.get("file_token"):
                continue
            blob = _download_bitable_attachment(file_meta["file_token"], headers, table)
            attachments.append({
                "kind": kind,
                "filename": str(file_meta.get("name") or f"{kind}_attachment"),
                "bytes": blob,
            })
    out["attachments"] = attachments
    return out

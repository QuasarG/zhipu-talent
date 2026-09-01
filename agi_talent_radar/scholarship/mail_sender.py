"""飞书用户身份邮件 + 多维表格回写：问卷确认信自动发送。

经 lark-cli（服务用户 talent-radar 的 HOME keyring 托管 token，自动刷新）。
发信：mailbox=zpsy@aminer.cn + from=zpsy@zhipuai.cn。
邮件成功后按电子邮箱定位新表记录，回写「是否回复并提醒=是」。

新表（tblAzD7mpEgvUSQ8）字段与问卷主表不同：
中文姓名 / 手机号码 / 电子邮箱｜Email Address（全角｜）/ 导师是否发送邮件推荐信 /
是否回复并提醒（select: 是/否）/ 自动编号 / 提交时间。
ponytail: 子进程调 CLI 免去 token 自管；表字段再改只动下方常量。
"""
from __future__ import annotations

import json
import subprocess
from datetime import date

_LARK_CLI = "/usr/bin/lark-cli"
# 总开关：False 时 webhook 同步照常，但完全不发信（灰度/调试用）
MAIL_ENABLED = True
# 邮件字体栈：MiSans 是网站自载字体，邮件客户端没有 → 必须用各端预装字体兜底
_MAIL_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
    "'Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',Arial,sans-serif"
)
_MAILBOX = "zpsy@aminer.cn"
_FROM = "zpsy@zhipuai.cn"
_BASE = "WMQxb6BhPar076sU40McQpYmnHg"
_TABLE = "tblAzD7mpEgvUSQ8"
_EMAIL_FIELD = "电子邮箱｜Email Address"
_REPLY_FIELD = "是否回复并提醒"


def mail_configured() -> bool:
    try:
        result = subprocess.run(
            [_LARK_CLI, "auth", "status"],
            capture_output=True, text=True, timeout=30,
        )
        # needs_refresh 表示 access token 过期但 refresh token 有效，lark-cli 调用时自动刷新
        return ('"tokenStatus": "valid"' in result.stdout
                or '"tokenStatus":"valid"' in result.stdout
                or '"tokenStatus": "needs_refresh"' in result.stdout
                or '"tokenStatus":"needs_refresh"' in result.stdout)
    except (OSError, subprocess.SubprocessError):
        return False


def _cli(args: list[str], timeout: int = 120) -> dict:
    result = subprocess.run(
        [_LARK_CLI, *args, "--format", "json"],
        capture_output=True, text=True, timeout=timeout,
    )
    out = result.stdout
    start = out.find("{")
    if start < 0:
        return {"ok": False, "error": {"message": f"cli 输出异常[{result.returncode}]: {(out + result.stderr)[:200]}"}}
    try:
        return json.loads(out[start:])
    except json.JSONDecodeError:
        return {"ok": False, "error": {"message": f"cli 返回不可解析: {out[:200]}"}}


def send_confirmation_email(to_email: str, applicant_name: str, is_update: bool = False, country: str = "", no_mark: bool = False, applicant_name_en: str = "") -> dict:
    """发确认邮件 → 成功后回写新表「是否回复并提醒=是」。

    is_update：修改提交后的再确认（文案区分 首次收到/已更新）。
    country：所在国家/地区——中国发中文版，其他发英文版。
    姓名随语言走：中文版用中文名（缺则英文名兜底），英文版用英文名（缺则中文名兜底）。
    no_mark：只发信不回写（链路灰度测试用）。
    返回 {sent, message_id?, marked?, error?, mark_error?}；
    邮件失败不回写；回写失败不影响邮件结果（journal 留痕）。
    """
    to_email = (to_email or "").strip()
    if not MAIL_ENABLED:
        return {"sent": False, "error": "邮件服务已停用（MAIL_ENABLED=False）"}
    if not to_email or "@" not in to_email:
        return {"sent": False, "error": f"申请人邮箱无效: {to_email!r}"}
    is_china = _is_china(country)
    zh_name = (applicant_name or "").strip() or (applicant_name_en or "").strip()
    en_name = (applicant_name_en or "").strip() or (applicant_name or "").strip()
    salutation = zh_name if is_china else en_name
    if is_china:
        subject = (
            "【Z.AI Scholarship 2026】申请材料已更新，确认已收到"
            if is_update else
            "【Z.AI Scholarship 2026】申请已收到"
        )
    else:
        subject = (
            "【Z.AI Scholarship 2026】Your updated application has been received"
            if is_update else
            "【Z.AI Scholarship 2026】Application received"
        )
    html = _render_template(salutation, date.today(), is_update=is_update, country=country)
    data = _cli([
        "mail", "+send",
        "--mailbox", _MAILBOX,
        "--from", _FROM,
        "--to", to_email,
        "--subject", subject,
        "--body", html,
        "--confirm-send",
    ])
    if not data.get("ok"):
        err = (data.get("error") or {}).get("message", "") or str(data.get("error", ""))[:200]
        return {"sent": False, "error": err}
    result = {
        "sent": True,
        "message_id": (data.get("data") or {}).get("message_id", ""),
    }
    if no_mark:
        return result
    marked, mark_err = mark_replied(to_email)
    result["marked"] = marked
    if not marked:
        result["mark_error"] = mark_err
    return result


def mark_replied(email: str) -> tuple[bool, str]:
    """按电子邮箱定位新表记录，回写 是否回复并提醒=是。"""
    record_id = _find_record_id(email)
    if not record_id:
        return False, f"新表未找到邮箱 {email} 对应记录"
    data = _cli([
        "base", "+record-upsert",
        "--base-token", _BASE,
        "--table-id", _TABLE,
        "--record-id", record_id,
        "--json", json.dumps({_REPLY_FIELD: ["是"]}, ensure_ascii=False),
    ], timeout=60)
    if data.get("ok"):
        return True, ""
    err = (data.get("error") or {}).get("message", "") or json.dumps(data.get("error", {}), ensure_ascii=False)[:150]
    return False, err


def _find_record_id(email: str) -> str:
    """分页扫表，按电子邮箱字段精确匹配（去空格小写）。"""
    page_token = ""
    for _ in range(20):
        args = [
            "base", "+record-list",
            "--base-token", _BASE,
            "--table-id", _TABLE,
            "--limit", "100",
        ]
        if page_token:
            args += ["--page-token", page_token]
        data = _cli(args, timeout=60)
        if not data.get("ok"):
            return ""
        payload = data.get("data") or {}
        fields = payload.get("fields") or []
        email_idx = next((i for i, f in enumerate(fields) if f == _EMAIL_FIELD), -1)
        rows = payload.get("data") or []
        ids = payload.get("record_id_list") or []
        if email_idx >= 0:
            target = email.strip().lower()
            for row_idx, row in enumerate(rows):
                val = row[email_idx] if email_idx < len(row) else ""
                if isinstance(val, str) and val.strip().lower() == target and row_idx < len(ids):
                    return ids[row_idx]
        if not payload.get("has_more"):
            return ""
        page_token = payload.get("page_token", "")
    return ""


def _is_china(country: str) -> bool:
    c = (country or "").strip()
    return "中国" in c or "china" in c.lower() or "PRC" in c.upper()


def _render_template(name: str, today: date, is_update: bool = False, country: str = "") -> str:
    """按所在国家/地区选语言：中国→中文，其他→英文。"""
    if _is_china(country):
        return _render_template_zh(name, today, is_update)
    return _render_template_en(name, today, is_update)


def _render_template_zh(name: str, today: date, is_update: bool) -> str:
    deadline = "<strong>2026年9月28日 24:00</strong>"
    signed = f"{today.year}年{today.month}月{today.day}日"
    opening = (
        "你修改后的申请材料已收到，本次评审将以最新提交为准。感谢你的关注与支持。"
        if is_update else
        "你的申请材料已收到，感谢你的关注与支持。"
    )
    return f"""<div style="font-family:{_MAIL_FONT};font-size:14px;line-height:1.9;color:#1a1a1a;max-width:640px">
<p>{name}同学：</p>
<p>你好！</p>
<p>{opening}</p>
<p><strong>特此提醒：</strong></p>
<ol style="padding-left:20px;margin:8px 0">
<li>请确保提交问卷时上传的材料完整无误，如有问题，可直接修改飞书问卷的提交记录，以最新的提交为准；</li>
<li>推荐信除随申请材料上传外，还需由导师本人将签署后的推荐信直接发送至项目邮箱 <strong>zpsy@zhipuai.cn</strong>。请提醒导师及时完成发送，截止时间为 {deadline}。</li>
<li>如有其他问题，欢迎随时与我们联系。邮箱：<strong>zpsy@zhipuai.cn</strong></li>
</ol>
<p>暑消秋至，祝安好！</p>
<p style="margin-top:24px"><strong>Z.AI Scholarship 项目组</strong><br/><strong>{signed}</strong></p>
</div>"""


def _render_template_en(name: str, today: date, is_update: bool) -> str:
    deadline = "<strong>September 28, 2026, 24:00 (UTC+8)</strong>"
    signed = f"{today.year}-{today.month:02d}-{today.day:02d}"
    opening = (
        "We have received your revised application materials. The review will be based on "
        "your latest submission. Thank you for your continued interest and support."
        if is_update else
        "We have received your application materials. Thank you for your interest and support."
    )
    return f"""<div style="font-family:{_MAIL_FONT};font-size:14px;line-height:1.9;color:#1a1a1a;max-width:640px">
<p>Dear {name},</p>
<p>{opening}</p>
<p><strong>Kind reminders:</strong></p>
<ol style="padding-left:20px;margin:8px 0">
<li>Please ensure the materials uploaded with your application are complete and correct. If there are any issues, you may edit your submission record in the Feishu form directly — the latest submission will be treated as final;</li>
<li>In addition to uploading the recommendation letter with your application, your advisor should send the signed letter directly to the program mailbox at <strong>zpsy@zhipuai.cn</strong>. Please kindly remind your advisor to send it before <strong>{deadline}</strong>;</li>
<li>Should you have any questions, feel free to contact us at <strong>zpsy@zhipuai.cn</strong>.</li>
</ol>
<p>Best regards,<br/><strong>Z.AI Scholarship Program Team</strong><br/>{signed}</p>
</div>"""

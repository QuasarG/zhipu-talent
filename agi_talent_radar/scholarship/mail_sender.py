"""飞书用户身份邮件：问卷确认信自动发送。

鉴权：user_access_token（refresh_token 轮换制，存 env）。token 不落盘、
每次启动从 FEISHU_USER_REFRESH_TOKEN 取，过期自动刷新并回写 env 文件。
（ponytail: 单机 env 存 refresh token，多实例部署时换集中式 secret 存储。）
发信：mailbox=zpsy@aminer.cn + from=zpsy@zhipuai.cn（公邮别名，实测可用）。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from datetime import date

_FEISHU_HOST = "https://open.feishu.cn"
_ENV_FILE = "/etc/zhipu-talent.env"

# 进程内 token 缓存（读 env → 调用 → 过期刷新 → 回写 env → 持久内存）
_LOCK = threading.Lock()
_TOKEN: dict = {"access": "", "expire_at": 0.0, "refresh": ""}


def mail_configured() -> bool:
    return bool(os.getenv("FEISHU_USER_REFRESH_TOKEN", "").strip())


def _env_read(key: str) -> str:
    try:
        with open(_ENV_FILE, encoding="utf-8") as fp:
            for line in fp:
                m = re.match(rf"^{key}=(.*)$", line.strip())
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return os.getenv(key, "").strip()


def _env_write(key: str, value: str) -> None:
    """刷新轮换后回写 env（root 服务进程可写）。"""
    try:
        with open(_ENV_FILE, encoding="utf-8") as fp:
            lines = fp.readlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}\n")
        with open(_ENV_FILE, "w", encoding="utf-8") as fp:
            fp.writelines(lines)
        os.environ[key] = value
    except OSError:
        pass  # env 不可写时只保内存（下次重启需人工更新）


def _http_json(url: str, payload: bytes | None, headers: dict, method: str = "POST") -> dict:
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _refresh_access_token() -> str:
    """refresh_token 换新 access_token；refresh 会轮换，需回写 env。"""
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    refresh = _TOKEN["refresh"] or _env_read("FEISHU_USER_REFRESH_TOKEN")
    if not (app_id and app_secret and refresh):
        raise RuntimeError("缺少 FEISHU_USER_REFRESH_TOKEN / FEISHU_APP_* 配置")
    data = _http_json(
        f"{_FEISHU_HOST}/open-apis/authen/v2/oauth/token",
        json.dumps({
            "grant_type": "refresh_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "refresh_token": refresh,
        }).encode(),
        {"Content-Type": "application/json"},
    )
    if data.get("code") not in (0, None):
        raise RuntimeError(f"刷新 user token 失败: {data.get('msg')}")
    _TOKEN["access"] = data["access_token"]
    _TOKEN["refresh"] = data["refresh_token"]
    _TOKEN["expire_at"] = time.time() + float(data.get("expires_in", 7200)) - 300
    _env_write("FEISHU_USER_REFRESH_TOKEN", _TOKEN["refresh"])
    return _TOKEN["access"]


def _access_token() -> str:
    with _LOCK:
        if _TOKEN["access"] and time.time() < _TOKEN["expire_at"]:
            return _TOKEN["access"]
        return _refresh_access_token()


def _build_eml(to_email: str, subject: str, html_body: str) -> bytes:
    import base64
    from email.message import EmailMessage
    from email.utils import formatdate

    mailbox = os.getenv("SCHOLARSHIP_MAIL_MAILBOX", "zpsy@aminer.cn").strip()
    sender = os.getenv("SCHOLARSHIP_MAIL_FROM", "zpsy@zhipuai.cn").strip()
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("请使用支持 HTML 的邮件客户端查看。")
    msg.add_alternative(html_body, subtype="html")
    return base64.urlsafe_b64encode(msg.as_bytes())


def send_confirmation_email(to_email: str, applicant_name: str) -> dict:
    """给申请人发确认邮件；返回 {sent: bool, message_id, error?}。"""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return {"sent": False, "error": f"申请人邮箱无效: {to_email!r}"}
    subject = "【智谱 Z.AI 奖学金】申请材料已收到"
    today = date.today()
    html = _render_template(applicant_name, today)
    mailbox = os.getenv("SCHOLARSHIP_MAIL_MAILBOX", "zpsy@aminer.cn").strip()
    raw = _build_eml(to_email, subject, html)

    token = _access_token()
    data = _http_json(
        f"{_FEISHU_HOST}/open-apis/mail/v1/user_mailboxes/{mailbox}/drafts",
        json.dumps({"raw": raw.decode(), "sender_mailbox": mailbox}).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    if data.get("code") not in (0, None):
        return {"sent": False, "error": f"建草稿失败: {data.get('msg')}"}
    draft_id = (data.get("data") or {}).get("draft_id") or ""
    send = _http_json(
        f"{_FEISHU_HOST}/open-apis/mail/v1/user_mailboxes/{mailbox}/drafts/{draft_id}/send",
        json.dumps({}).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    if send.get("code") not in (0, None):
        return {"sent": False, "error": f"发送失败: {send.get('msg')}", "draft_id": draft_id}
    return {"sent": True, "message_id": draft_id}


def _render_template(name: str, today: date) -> str:
    deadline = "2026年9月28日 24:00"
    signed = today.strftime("%Y年%m月%d日").lstrip("0")
    signed = re.sub(r"年0?", "年", signed).replace("月0", "月")
    return f"""<div style="font-family:MiSans,system-ui,sans-serif;font-size:14px;line-height:1.9;color:#1a1a1a;max-width:640px">
<p>{name}同学：</p>
<p>你好！</p>
<p>你的申请材料已收到，感谢你的关注与支持。</p>
<p><strong>特此提醒：</strong></p>
<ol style="padding-left:20px;margin:8px 0">
<li>请确保提交问卷时上传的材料完整无误，如有问题，可直接修改飞书问卷的提交记录，以最新的提交为准；</li>
<li>推荐信除随申请材料上传外，还需由导师本人将签署后的推荐信直接发送至项目邮箱 zpsy@zhipuai.cn。请提醒导师及时完成发送，截止时间为 {deadline}。</li>
<li>如有其他问题，欢迎随时与我们联系。邮箱：zpsy@zhipuai.cn</li>
</ol>
<p>暑消秋至，祝安好！</p>
<p style="margin-top:24px">Z.AI Scholarship 项目组<br/>{signed}</p>
</div>"""

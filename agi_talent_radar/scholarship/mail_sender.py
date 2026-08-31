"""飞书用户身份邮件：问卷确认信自动发送（经 lark-cli，token/刷新由其托管）。

服务用户（talent-radar）需一次 device-flow 登录（HOME 下 keyring 持久化，
refresh 自动轮换）。发信：mailbox=zpsy@aminer.cn + from=zpsy@zhipuai.cn。
ponytail: 子进程调 CLI 比 HTTP+token 自管少 200 行刷新/回写逻辑，单机够用。
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date

_LARK_CLI = "/usr/bin/lark-cli"
_MAILBOX = "zpsy@aminer.cn"
_FROM = "zpsy@zhipuai.cn"


def mail_configured() -> bool:
    return _probe_cli()


def _probe_cli() -> bool:
    try:
        result = subprocess.run(
            [_LARK_CLI, "auth", "status"],
            capture_output=True, text=True, timeout=30,
        )
        return '"tokenStatus": "valid"' in result.stdout or '"tokenStatus":"valid"' in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def send_confirmation_email(to_email: str, applicant_name: str) -> dict:
    """给申请人发确认邮件；返回 {sent: bool, message_id?, error?}。"""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return {"sent": False, "error": f"申请人邮箱无效: {to_email!r}"}
    subject = "【智谱 Z.AI 奖学金】申请材料已收到"
    html = _render_template(applicant_name, date.today())
    try:
        result = subprocess.run(
            [
                _LARK_CLI, "mail", "+send",
                "--mailbox", _MAILBOX,
                "--from", _FROM,
                "--to", to_email,
                "--subject", subject,
                "--body", html,
                "--confirm-send",
                "--format", "json",
            ],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"sent": False, "error": "发送超时(120s)"}
    out = result.stdout
    start = out.find("{")
    if start < 0:
        return {"sent": False, "error": f"cli 输出异常: {out[:200]}"}
    try:
        data = json.loads(out[start:])
    except json.JSONDecodeError:
        return {"sent": False, "error": f"cli 返回不可解析: {out[:200]}"}
    if data.get("ok"):
        return {"sent": True, "message_id": (data.get("data") or {}).get("message_id", "")}
    err = (data.get("error") or {}).get("message", "") or out[:200]
    return {"sent": False, "error": err}


def _render_template(name: str, today: date) -> str:
    deadline = "<strong>2026年9月28日 24:00</strong>"
    # 手动去零（%-m 仅 Linux 支持，服务端与本地测试都要能跑）
    signed = f"{today.year}年{today.month}月{today.day}日"
    return f"""<div style="font-family:MiSans,system-ui,sans-serif;font-size:14px;line-height:1.9;color:#1a1a1a;max-width:640px">
<p>{name}同学：</p>
<p>你好！</p>
<p>你的申请材料已收到，感谢你的关注与支持。</p>
<p><strong>特此提醒：</strong></p>
<ol style="padding-left:20px;margin:8px 0">
<li>请确保提交问卷时上传的材料完整无误，如有问题，可直接修改飞书问卷的提交记录，以最新的提交为准；</li>
<li>推荐信除随申请材料上传外，还需由导师本人将签署后的推荐信直接发送至项目邮箱 <strong>zpsy@zhipuai.cn</strong>。请提醒导师及时完成发送，截止时间为 {deadline}。</li>
<li>如有其他问题，欢迎随时与我们联系。邮箱：<strong>zpsy@zhipuai.cn</strong></li>
</ol>
<p>暑消秋至，祝安好！</p>
<p style="margin-top:24px"><strong>Z.AI Scholarship 项目组</strong><br/><strong>{signed}</strong></p>
</div>"""

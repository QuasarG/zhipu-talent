"""入库前 LLM 语义解析层：把飞书问卷原始字段清洗成结构化形态。

解决规则正则处理不了的语义级混乱：
- 导师姓名连写拆不开（"Bryan Hooi Jiaheng Zhang" 是两个人）
- 导师职务描述和姓名糊在一起（两人描述挤一根 VARCHAR）
- 方向字段「、｜」双层分隔符拼接串
- 年级/学位/毕业时间的口语化写法

防幻觉红线：LLM 只做「拆分/规范化/重排」，不做「补全」——
每个产出字段都要过确定性校验（字符集比对），校验不过保持原值。
advisors 校验失败保留规则 split 结果：宁可格式丑，不能人名错。
LLM 不可用时整体降级为旧规则行为，webhook 永不因解析层 4xx/5xx。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 规则层的 advisors 兜底切分（保持与 feishu_pull 一致的分隔符集）
_ADVISOR_SPLIT = re.compile(r"[、,，;；/]")


def _norm(s: Any) -> str:
    """压空白：姓名/标题类字段不允许内部换行和连续空格。"""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _chars(text: str) -> set[str]:
    """字符多重集：比对「LLM 是否只是重排了原文，没发明新内容」。"""
    return set(re.sub(r"[\s、，,;；/｜|·•()（）]", "", text or ""))


def parse_fields(raw: dict[str, Any], llm: Callable[..., dict] | None = None) -> dict[str, Any]:
    """主入口：原始飞书 payload → 清洗后的字段补丁（只含需要覆盖的键）。

    返回键：advisors / advisor_title / direction / grade / degree_type /
    expected_graduation / school / lab。校验失败或缺值的键不出现在返回里，
    由调用方保持原值。
    """
    try:
        llm = llm or _default_llm()
        return _parse(raw, llm)
    except Exception as exc:  # noqa: BLE001 — 解析层永不阻断入库
        logger.warning("LLM 字段解析失败，降级规则清洗：%s", exc)
        return _fallback(raw)


def _default_llm() -> Callable[..., dict]:
    from agi_talent_radar.core.llm_client import call_llm_json

    return call_llm_json


_PARSE_PROMPT = """你是问卷字段清洗器。输入是奖学金申请表单的原始字段（中文表单，
申请人填什么都可能）。只做拆分、规范化、重排，禁止补全或发明原文没有的信息。

任务：
1. advisors_raw → advisors：拆成独立的导师姓名列表。"Bryan Hooi Jiaheng Zhang"
   是 Bryan Hooi 和 Jiaheng Zhang 两个人；中文姓名按常见长度切分；混合中英文
   顿号/逗号/空格连写都要拆。每个名字内部多余空格压缩成一个。
2. advisor_title_raw → advisor_title：两位导师各自的单位职务，用 "；" 连接成
   一行（如 "Bryan Hooi，NUS 助理教授；Jiaheng Zhang，NUS 助理教授"）。
   只重排原文信息，不新增头衔。
3. direction_raw → directions：把「、」「｜」等分隔符拼接的方向串拆成独立方向
   列表；中英文同义对（如"基础模型丨Foundation Models"）保留成一项
   "基础模型 Foundation Models"（空格连接，去重）。
4. grade_raw → grade_norm / degree_type / grad_year_month：
   - grade_norm：规范年级文案，如 "博士三年级" / "硕士一年级"
   - degree_type：只能是 "phd" 或 "master"（都不符合给 ""）
   - grad_year_month：预计毕业 → "YYYY-MM"；解析不出给 ""
5. school_raw → school_norm：规范学校名（全称，原文没有全称就用原样）。
6. lab_raw → lab_norm：院系/实验室名规范（去多余分隔符）。

只输出 JSON：
{"advisors": ["..."], "advisor_title": "...", "directions": ["..."],
 "grade_norm": "...", "degree_type": "phd|master|", "grad_year_month": "YYYY-MM",
 "school_norm": "...", "lab_norm": "..."}"""


def _parse(raw: dict[str, Any], llm: Callable[..., dict]) -> dict[str, Any]:
    payload = {
        "advisors_raw": _norm(raw.get("advisors_raw")),
        "advisor_title_raw": _norm(raw.get("advisor_title_raw")),
        "direction_raw": _norm(raw.get("direction_raw")),
        "grade_raw": _norm(raw.get("grade_raw")),
        "school_raw": _norm(raw.get("school_raw")),
        "lab_raw": _norm(raw.get("lab_raw")),
        "grad_raw": _norm(raw.get("grad_raw")),
    }
    if not any(payload.values()):
        return {}
    data = llm(_PARSE_PROMPT, payload)
    patch: dict[str, Any] = {}

    # 导师姓名：多重集校验（LLM 只能重排，不能造名字）
    advisors = [_norm(a) for a in (data.get("advisors") or []) if _norm(a)]
    raw_advisors = payload["advisors_raw"]
    if raw_advisors and advisors and _chars("".join(advisors)) <= _chars(raw_advisors):
        patch["advisors"] = advisors
    elif raw_advisors:
        patch["advisors"] = _rule_split_advisors(raw_advisors)

    title = _norm(data.get("advisor_title"))
    if title and payload["advisor_title_raw"] and _chars(title) <= _chars(payload["advisor_title_raw"]) | _chars(raw_advisors):
        patch["advisor_title"] = title[:250]

    # 方向：产出比原文更可读的合并形态（允许中英文对合并成一项）
    directions = [_norm(d) for d in (data.get("directions") or []) if _norm(d)]
    if directions and payload["direction_raw"] and _chars("".join(directions)) <= _chars(payload["direction_raw"]):
        patch["direction"] = "；".join(directions)[:250]

    grade_norm = _norm(data.get("grade_norm"))
    if grade_norm and _chars(grade_norm) <= _chars(payload["grade_raw"]):
        patch["grade"] = grade_norm
    degree = str(data.get("degree_type") or "")
    if degree in ("phd", "master"):
        patch["degree_type"] = degree

    month = str(data.get("grad_year_month") or "")
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        patch["expected_graduation"] = month

    school_norm = _norm(data.get("school_norm"))
    if school_norm and _chars(school_norm) <= _chars(payload["school_raw"]):
        patch["school"] = school_norm[:250]
    lab_norm = _norm(data.get("lab_norm"))
    if lab_norm and _chars(lab_norm) <= _chars(payload["lab_raw"]):
        patch["lab"] = lab_norm[:250]
    return patch


def _rule_split_advisors(text: str) -> list[str]:
    parts = [_norm(p) for p in _ADVISOR_SPLIT.split(text)]
    return [p for p in parts if p]


def _fallback(raw: dict[str, Any]) -> dict[str, Any]:
    """LLM 不可用/失败时的纯规则兜底（与旧行为一致，外加基础清洗）。"""
    patch: dict[str, Any] = {}
    raw_advisors = _norm(raw.get("advisors_raw"))
    if raw_advisors:
        patch["advisors"] = _rule_split_advisors(raw_advisors)
    direction = _norm(raw.get("direction_raw"))
    if direction:
        # 规则兜底：统一分隔符为 ；
        merged = re.split(r"[、｜|]", direction)
        patch["direction"] = "；".join(m for m in (_norm(x) for x in merged) if m)[:250]
    return patch


def wants_parsing(raw: dict[str, Any]) -> bool:
    """快速判断是否值得调 LLM：有任意可清洗字段即真。"""
    keys = ("advisors_raw", "advisor_title_raw", "direction_raw", "grade_raw",
            "school_raw", "lab_raw", "grad_raw")
    return any(_norm(raw.get(k)) for k in keys)

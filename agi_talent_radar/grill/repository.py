"""grill 会话持久化：GrillSessionORM 的 DAO（扁平函数风格，对齐项目 repository.py）。

单表 grill_sessions 承载一次澄清全过程：画像卡 / 提问大纲 / 对话历史 / 交付物。
保留 grill 原 state.py 的接口形状（get/save/check_converged/empty_profile），
让 tools.py / loop.py 改动最小；ownership 由 api 层在校验后调用本模块。
"""
from __future__ import annotations

import threading
from typing import Any

from agi_talent_radar.core.db.orm import GrillSessionORM
from agi_talent_radar.core.db.runtime import get_session

CONFIDENCE_THRESHOLD = 0.8

# 进程内锁：保护 running 标志的 check-then-set（防同一会话并发澄清）
_LOCK = threading.Lock()

# 画像卡必填/选填字段定义（label 与 PRD §3 对齐）
REQUIRED_FIELDS = {
    "position_name": "岗位名称",
    "job_category": "岗位类别",
    "degree_min": "学历门槛",
    "graduation_window": "届别/毕业时间",
    "base_city": "Base 地",
    "hard_skills": "核心技术要求",
    "must_have_experience": "必备经历",
}
OPTIONAL_FIELDS = {
    "bonus_items": "加分项",
    "soft_traits": "软素质偏好",
    "target_schools": "目标院校倾向",
    "team_fit": "团队匹配/培养预期",
}


def empty_profile() -> dict[str, Any]:
    def field(label: str) -> dict[str, Any]:
        return {"label": label, "value": None, "confidence": 0.0, "evidence": "", "status": "empty"}

    return {
        "required_fields": {k: field(v) for k, v in REQUIRED_FIELDS.items()},
        "optional_fields": {k: field(v) for k, v in OPTIONAL_FIELDS.items()},
        "conflicts": [],
        "converged": False,
    }


def create_session(owner_id: str) -> dict[str, Any]:
    with get_session() as db:
        rec = GrillSessionORM(
            owner_id=owner_id,
            profile=empty_profile(),
            outline=[],
            messages=[],
            deliverables=None,
            converged=False,
            running=False,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        sid = rec.id
    return get_session_by_id(sid)  # type: ignore[return-value]


def get_session_by_id(sid: str) -> dict[str, Any] | None:
    """工具层读取入口：返回序列化后的会话 dict（信任 api 层已校验 ownership）。"""
    with get_session() as db:
        rec = db.get(GrillSessionORM, sid)
        if rec is None:
            return None
        return _to_dict(rec)


def save_session(sid: str, **fields: Any) -> None:
    """可更新键：profile / outline / messages / deliverables / converged / running。"""
    with get_session() as db:
        rec = db.get(GrillSessionORM, sid)
        if rec is None:
            return
        for key, value in fields.items():
            if key in ("profile", "outline", "messages", "deliverables"):
                setattr(rec, key, value)
            elif key == "converged":
                rec.converged = bool(value)
            elif key == "running":
                rec.running = bool(value)
        db.commit()


def delete_sessions(sids: list[str], owner_id: str) -> int:
    with get_session() as db:
        n = (
            db.query(GrillSessionORM)
            .filter(GrillSessionORM.id.in_(sids), GrillSessionORM.owner_id == owner_id)
            .delete(synchronize_session=False)
        )
        db.commit()
    return n


def list_sessions(owner_id: str) -> list[dict[str, Any]]:
    with get_session() as db:
        recs = (
            db.query(GrillSessionORM)
            .filter_by(owner_id=owner_id)
            .order_by(GrillSessionORM.updated_at.desc())
            .all()
        )
        out = []
        for rec in recs:
            sess = _to_dict(rec)
            out.append({
                "session_id": sess["session_id"],
                "title": title_of(sess),
                "created_at": sess["created_at"],
                "updated_at": sess["updated_at"],
                "status": "已交付" if sess["deliverables"] else ("已澄清" if sess["converged"] else "进行中"),
            })
    return out


def check_converged(profile: dict[str, Any]) -> bool:
    return all(
        float(f.get("confidence") or 0) >= CONFIDENCE_THRESHOLD
        for f in profile.get("required_fields", {}).values()
    )


def try_set_running(sid: str) -> bool:
    """原子地抢占 running 标志：成功返回 True，已在跑返回 False。"""
    with _LOCK, get_session() as db:
        rec = db.get(GrillSessionORM, sid)
        if rec is None or rec.running:
            return False
        rec.running = True
        db.commit()
        return True


def clear_running(sid: str) -> None:
    with get_session() as db:
        rec = db.get(GrillSessionORM, sid)
        if rec is not None:
            rec.running = False
            db.commit()


def clear_all_running() -> None:
    """进程启动时清零：重启意味着所有 worker 线程已死。"""
    with get_session() as db:
        db.query(GrillSessionORM).filter(GrillSessionORM.running.is_(True)).update(
            {GrillSessionORM.running: False}, synchronize_session=False
        )
        db.commit()


def title_of(sess: dict[str, Any]) -> str:
    pos = (sess["profile"].get("required_fields", {}).get("position_name") or {}).get("value")
    if isinstance(pos, list):
        pos = "、".join(map(str, pos))
    if pos:
        return str(pos)[:30]
    for m in sess["messages"]:
        if m.get("role") == "user" and str(m.get("text") or "").strip():
            return str(m["text"]).strip()[:20]
    return "未命名会话"


def _to_dict(rec: GrillSessionORM) -> dict[str, Any]:
    return {
        "session_id": rec.id,
        "owner_id": rec.owner_id,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        "profile": rec.profile or empty_profile(),
        "outline": rec.outline or [],
        "messages": rec.messages or [],
        "deliverables": rec.deliverables,
        "converged": bool(rec.converged),
        "running": bool(rec.running),
    }

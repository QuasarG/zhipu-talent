"""panel 评审团自检：主席循环、工种白名单、会话续派、装配规则、评分合同同构。

FakeLLM 脚本化，不打外网。跑法：python3 tests/test_job_fit_panel.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agi_talent_radar.agents.job_fit.evaluator import DIMENSIONS, _build_evaluation
from agi_talent_radar.agents.job_fit.panel import (
    MaterialsContext,
    _evidence_quality,
    build_dossier,
    run_mission,
    run_panel_stream,
)
from agi_talent_radar.core.models import JobDefinition
from agi_talent_radar.core.runner import _validated_jobs  # noqa: F401  确认 runner 可导入
from agi_talent_radar.agents.job_fit.nodes import run_decision_guard, run_job_fit_formatter

LLM = "agi_talent_radar.core.llm_client"

RESUME_DUMP = {
    "id": "c1", "name": "张三", "target_role": "LLM 工程师", "stage": "校招",
    "raw_text": "张三，三年经验", "source_format": "pdf",
    "experiences": ["某公司 LLM 工程师，三年经验"],
    "publications": ["Deep Paper"],
}

JOB = JobDefinition(
    id="jd1", title="LLM 工程师", raw_text="要求：三年 LLM 经验，熟悉 RAG。",
    spec={"dimensions": [{"key": "d1", "label": "工程落地", "max_points": 30, "evidence_rule": "看上线证据"}],
          "keywords": ["llm", "rag"], "high_score_rule": "有上线与指标", "evidence_focus": "工程证据"},
)


def _mk_ctx() -> tuple[MaterialsContext, str]:
    tmp = tempfile.mkdtemp()
    (Path(tmp) / "a.txt").write_text("alpha beta content\n" * 50, encoding="utf-8")
    return MaterialsContext(tmp, None), tmp


def _consume(gen):
    events = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        return events, stop.value


class _FakeTools:
    """tools 非空按脚本走；tools==[]（JSON 通道）按 mission 类型回 findings。"""

    def __init__(self, tool_script: list[dict], findings: dict[str, str]):
        self.tool_script = list(tool_script)
        self.findings = findings

    def __call__(self, messages, tools, **kwargs):
        if tools:
            return self.tool_script.pop(0) if self.tool_script else {"text": "", "tool_calls": []}
        system = messages[0]["content"]
        for key, marker in (("verify", "证据查证评审员"), ("jd_match", "岗位对照评审员"),
                            ("deep_read", "深读评审员"), ("generic", "通用评审员")):
            if marker in system:
                return {"text": self.findings[key], "tool_calls": []}
        return {"text": self.findings["generic"], "tool_calls": []}


FINDINGS_VERIFY = json.dumps({"claims": [
    {"claim": "Deep Paper", "verdict": "verified", "source": "ACL", "quote": "随便"},
    {"claim": "内部项目奖", "verdict": "claimed", "source": "a.txt", "quote": "alpha beta content"},
]}, ensure_ascii=False)

FINDINGS_JD_MATCH = json.dumps({"assessments": [{
    "jd_id": "jd1",
    "hard_requirements": [
        {"requirement": "三年 LLM 经验", "status": "met", "evidence": ["三年经验"], "rationale": "简历明确写了"},
        {"requirement": "熟悉 RAG", "status": "met", "evidence": ["简历里没这句"], "rationale": "幻觉引文应被剔除"},
    ],
    "dimensions": [
        {"key": "direct_task_match", "score": 4, "rationale": "简历显示做过 LLM 工程核心工作内容充分", "evidence": ["三年经验"]},
    ],
}]}, ensure_ascii=False)


def _chair_dispatch() -> dict:
    return {"action": "dispatch", "missions": [
        {"mission_id": "m1", "type": "verify", "goal": "查证论文与奖项",
         "files": ["a.txt"], "resume_claims": ["Deep Paper"]},
        {"mission_id": "m2", "type": "jd_match", "goal": "对照 jd1 判硬门槛", "jd_id": "jd1"},
    ]}


def _chair_synthesize() -> dict:
    return {"action": "synthesize", "per_jd": [{
        "jd_id": "jd1", "confidence": 0.8,
        "strengths": [{"summary": "工程落地扎实", "evidence": ["a.txt"]}],
        "risks": [], "interview_questions": ["介绍一下 RAG 项目?"],
        "missing_information": ["成绩单未提供"], "assessment_summary": "值得面",
    }]}


class PanelEndToEndTests(unittest.TestCase):
    def test_dispatch_synthesize_produces_contract_valid_raw(self) -> None:
        ctx, _ = _mk_ctx()
        tools = _FakeTools(
            tool_script=[{"text": "", "tool_calls": [
                {"id": "t1", "name": "read_text", "arguments": json.dumps({"file": "a.txt", "page": 0})}]}],
            findings={"verify": FINDINGS_VERIFY, "jd_match": FINDINGS_JD_MATCH},
        )
        with patch(f"{LLM}.call_llm_json", side_effect=[_chair_dispatch(), _chair_synthesize()]), \
             patch(f"{LLM}.call_llm_tools", side_effect=tools):
            events, raw = _consume(run_panel_stream(RESUME_DUMP, [JOB], None, ctx))

        nodes = [e["message"] for e in events if e["type"] == "node"]
        self.assertTrue(any("材料整备" in e["label"] for e in events if e["type"] == "node"))
        self.assertTrue(any("任务[m1]" in m for m in nodes))
        dispatches = [e for e in events if e.get("event_kind") == "dispatch"]
        self.assertEqual([(e["agent_id"], e["target_id"]) for e in dispatches], [("chair", "m1"), ("chair", "m2")])
        self.assertEqual(dispatches[0]["detail"]["目标"], "查证论文与奖项")
        returns = [e for e in events if e.get("event_kind") == "handoff" and e.get("target_id") == "chair"]
        self.assertEqual([e["agent_id"] for e in returns], ["m1", "m2"])
        self.assertTrue(returns[0]["detail"]["主席收到的摘要"])
        calls = [e for e in events if e.get("call_id") == "t1"]
        self.assertEqual([e["event_kind"] for e in calls], ["tool_call", "tool_result"])
        self.assertEqual(calls[0]["detail"]["输入"]["file"], "a.txt")

        a = raw["assessments"][0]
        self.assertEqual(a["jd_id"], "jd1")
        self.assertEqual({d["key"] for d in a["dimensions"]}, {k for k, _l, _w in DIMENSIONS})
        by_key = {d["key"]: d for d in a["dimensions"]}
        self.assertEqual(by_key["direct_task_match"]["score"], 4.0)
        self.assertEqual(by_key["evidence_quality"]["score"], 3.4)  # (1.0+0.2)/2 → 1+4*0.6
        self.assertIn("证据核验 2 条", by_key["evidence_quality"]["rationale"])
        for key in ("technical_depth", "ownership", "engineering_scale", "transferability"):
            self.assertEqual(by_key[key]["score"], 2.0)
            self.assertIn("未覆盖", by_key[key]["rationale"])
        self.assertEqual(len(a["hard_requirements"]), 2)
        # 幻觉引文「简历里没这句」被反查剔除；真实引文保留
        met_ev = [r for r in a["hard_requirements"] if r["requirement"] == "熟悉 RAG"][0]["evidence"]
        self.assertEqual(met_ev, [])
        self.assertIn("主席未产出" not in "".join(a["missing_information"]), [True])
        self.assertIn("成绩单未提供", a["missing_information"])
        self.assertEqual(a["confidence"], 0.4)  # 0.8 × 0.5（缺维降级）

        # 评分合同同构：raw 能过确定性门槛并组装出最终输出
        state = {"prepared_resume": RESUME_DUMP, "prepared_jobs": [JOB.model_dump()], "job_fit_raw": raw}
        state.update(run_decision_guard(state))
        state.update(run_job_fit_formatter(state))
        self.assertEqual(state["final_output"]["interview_decision"], "hold")  # 56.2 分：hold 档
        self.assertEqual(state["final_output"]["best_fit_jd_id"], "jd1")

    def test_chair_always_invalid_degrades_to_scored_result(self) -> None:
        ctx, _ = _mk_ctx()
        with patch.dict(os.environ, {"PANEL_LEAD_MAX_ROUNDS": "1"}), \
             patch(f"{LLM}.call_llm_json", return_value={"action": "nonsense"}), \
             patch(f"{LLM}.call_llm_tools", return_value={"text": "", "tool_calls": []}):
            _events, raw = _consume(run_panel_stream(RESUME_DUMP, [JOB], None, ctx))
        a = raw["assessments"][0]
        self.assertIn("主席未产出综合意见", a["missing_information"])
        self.assertEqual(len(a["dimensions"]), 6)  # 照常出分
        eq = [d for d in a["dimensions"] if d["key"] == "evidence_quality"][0]
        self.assertEqual(eq["score"], 2.5)  # 有论文未查证 → NO_VERIFY_SCORE

    def test_no_verify_without_publications_defaults_low(self) -> None:
        ctx, _ = _mk_ctx()
        dump = {**RESUME_DUMP, "publications": []}
        with patch.dict(os.environ, {"PANEL_LEAD_MAX_ROUNDS": "1"}), \
             patch(f"{LLM}.call_llm_json", return_value={"action": "nonsense"}), \
             patch(f"{LLM}.call_llm_tools", return_value={"text": "", "tool_calls": []}):
            _events, raw = _consume(run_panel_stream(dump, [JOB], None, ctx))
        eq = [d for d in raw["assessments"][0]["dimensions"] if d["key"] == "evidence_quality"][0]
        self.assertEqual(eq["score"], 2.0)  # 无论文且未查证 → MISSING_DIM_SCORE


class MissionRunnerTests(unittest.TestCase):
    def test_tool_whitelist_is_enforced_in_code(self) -> None:
        ctx, _ = _mk_ctx()
        mission = {"mission_id": "m1", "type": "deep_read", "goal": "深读",
                   "dimensions": ["technical_depth"]}
        findings = json.dumps({"assessments": [{"jd_id": "jd1", "dimensions": [
            {"key": "technical_depth", "score": 3.5, "rationale": "材料显示方法有细节和对比实验充分", "evidence": ["alpha beta content"]}]}]},
            ensure_ascii=False)
        tools = _FakeTools(
            tool_script=[{"text": "", "tool_calls": [
                {"id": "t1", "name": "web_search", "arguments": json.dumps({"query": "越权调用"})}]}],
            findings={"deep_read": findings},
        )
        sessions: dict[str, list] = {}
        lifetime: dict[str, int] = {}
        with patch(f"{LLM}.call_llm_tools", side_effect=tools):
            _events, outcome = _consume(run_mission(mission, {"resume": RESUME_DUMP, "files": [], "jobs": []},
                                                    ctx, sessions, lifetime))
        self.assertEqual(outcome["status"], "done")
        tool_msg = [m for m in sessions["m1"] if m.get("role") == "tool"]
        self.assertIn("不属于工种", json.dumps(tool_msg, ensure_ascii=False))

    def test_resume_reuses_stored_session(self) -> None:
        ctx, _ = _mk_ctx()
        dossier = {"resume": RESUME_DUMP, "files": [], "jobs": []}
        sessions: dict[str, list] = {}
        lifetime: dict[str, int] = {}
        findings = json.dumps({"arbitrations": [
            {"question": "贡献归属?", "conclusion": "材料支持本人主导", "quotes": []}]}, ensure_ascii=False)
        tools = _FakeTools(tool_script=[], findings={"generic": findings, "cross_check": findings})
        with patch(f"{LLM}.call_llm_tools", side_effect=tools):
            _consume(run_mission({"mission_id": "m9", "type": "generic", "goal": "首轮"},
                                 dossier, ctx, sessions, lifetime))
            first_len = len(sessions["m9"])
            _consume(run_mission({"mission_id": "m9", "type": "cross_check", "goal": "仲裁",
                                  "note_to_worker": "复核第3段"}, dossier, ctx, sessions, lifetime))
        self.assertGreater(len(sessions["m9"]), first_len)  # 续派在原上下文追加，而非新开
        resumed_user = [m for m in sessions["m9"] if m.get("role") == "user" and "主席" in str(m.get("content"))]
        self.assertTrue(any("复核第3段" in m["content"] for m in resumed_user))
        self.assertEqual(lifetime["m9"], 0)  # 两轮都直接交 findings，没有工具轮


class AssemblyUnitTests(unittest.TestCase):
    def test_evidence_quality_mapping(self) -> None:
        score, _, _ = _evidence_quality([{"verdict": "verified"}, {"verdict": "verified"}], [])
        self.assertEqual(score, 5.0)
        score, _, _ = _evidence_quality([{"verdict": "verified"}, {"verdict": "claimed"}], [])
        self.assertEqual(score, 3.4)  # 1 + 4×0.6
        # 代表作 claimed 反通胀封顶：原始 3.4 压到 2.5（封顶是上限，不托底）
        claims = [{"claim": "Deep Paper v2 一作", "verdict": "verified"},
                  {"claim": "Deep Paper v2 会议版", "verdict": "claimed"}]
        score, _, note = _evidence_quality(claims, ["Deep Paper v2"])
        self.assertEqual(score, 2.5)
        self.assertIn("代表作", note)
        score, _, _ = _evidence_quality([{"claim": "别的成果", "verdict": "claimed"}], ["Deep Paper v2"])
        self.assertEqual(score, 1.8)  # 与代表作无关的 claimed 不触发封顶
        self.assertIsNone(_evidence_quality([], [])[0])


class DossierTests(unittest.TestCase):
    def test_dossier_probes_text_layer_and_keeps_jd_raw_away_from_chair_payload(self) -> None:
        ctx, _ = _mk_ctx()
        dossier = build_dossier(RESUME_DUMP, [JOB], {"verified": 1}, ctx)
        self.assertTrue(dossier["files"][0]["text_layer"])
        self.assertEqual(dossier["files"][0]["segments"], 1)
        self.assertEqual(dossier["jobs"][0]["jd_id"], "jd1")
        self.assertTrue(dossier["jobs"][0]["has_spec"])
        self.assertIn("三年 LLM 经验", dossier["jd_raw_map"]["jd1"])
        from agi_talent_radar.agents.job_fit.panel import _lead_payload
        payload = json.dumps(_lead_payload(dossier, [], 3))
        self.assertNotIn("三年 LLM 经验，熟悉", payload)  # JD 全文不进主席上下文（只有 400 字摘录）


if __name__ == "__main__":
    unittest.main()

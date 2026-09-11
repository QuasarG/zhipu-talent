"""panel v2 自检：主 agent spawn 流、子 agent 禁止嵌套、预算、评分合同兜底、装配缺维降级。

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

from agi_talent_radar.agents.job_fit.evaluator import DIMENSIONS
from agi_talent_radar.agents.job_fit.materials import MaterialsContext
from agi_talent_radar.agents.job_fit.panel import (
    WORKER_TOOLS,
    assemble,
    build_dossier,
    run_agent_mission,
    run_panel_stream,
)
from agi_talent_radar.agents.job_fit.nodes import run_decision_guard, run_job_fit_formatter
from agi_talent_radar.core.models import JobDefinition

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

SPAWN_PROMPT = "精读 paper.pdf，核查论文真实性并评估技术深度，报告引用到页。"


def _contract(**overrides) -> dict:
    assessment = {
        "jd_id": "jd1",
        "hard_requirements": [],
        "dimensions": [
            {"key": "direct_task_match", "score": 4, "rationale": "有直接证据支撑判断充分", "evidence": []},
            {"key": "evidence_quality", "score": 3, "rationale": "公开源已查证充分", "evidence": []},
        ],
        "confidence": 0.8,
        "strengths": [], "risks": [], "missing_information": [],
        "interview_questions": ["介绍一下 RAG 项目?"],
        "assessment_summary": "值得面",
    }
    assessment.update(overrides)
    return {"assessments": [assessment]}


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


class FakePanelLLM:
    """tools 非空按 system 区分主席/子 agent 脚本；tools==[] 为收尾 JSON 通道。"""

    def __init__(self, chair_script: list[dict], worker_script: list[dict], contract: dict):
        self.chair_script = list(chair_script)
        self.worker_script = list(worker_script)
        self.contract = contract
        self.tool_contents: list[str] = []
        self.final_calls = 0

    def __call__(self, messages: list[dict], tools: list, **kwargs):
        self.tool_contents.extend(
            m.get("content", "") for m in messages if m.get("role") == "tool")
        if not tools:
            self.final_calls += 1
            return {"text": json.dumps(self.contract, ensure_ascii=False), "tool_calls": []}
        system = messages[0]["content"]
        script = self.chair_script if "主席（主 agent）" in system else self.worker_script
        return script.pop(0) if script else {"text": "报告", "tool_calls": []}

    def tool_calls_of(self, name: str) -> list[dict]:
        return [tc for tc in self.chair_script + self.worker_script
                if any(c["name"] == name for c in tc.get("tool_calls", []))]


def _spawn_call() -> dict:
    return {"text": "", "tool_calls": [
        {"id": "t1", "name": "spawn_agent",
         "arguments": json.dumps({"goal": "核查论文", "prompt": SPAWN_PROMPT}, ensure_ascii=False)}]}


def _read_call() -> dict:
    return {"text": "", "tool_calls": [
        {"id": "w1", "name": "read_text",
         "arguments": json.dumps({"file": "a.txt", "page": 0})}]}


class PanelEndToEndTests(unittest.TestCase):
    def test_chair_spawns_worker_and_contract_assembles(self) -> None:
        ctx, _ = _mk_ctx()
        fake = FakePanelLLM(
            chair_script=[_spawn_call(), {"text": "报告已收齐，收工。", "tool_calls": []}],
            worker_script=[_read_call(), {"text": "## 评审报告\n贡献充分，引用到页。", "tool_calls": []}],
            contract=_contract(),
        )
        with patch(f"{LLM}.call_llm_tools", side_effect=fake):
            events, raw = _consume(run_panel_stream(RESUME_DUMP, [JOB], None, ctx))

        # 事件流：派工 → 子 agent 请求/工具/说明 → 报告回传 → 主席发言
        dispatches = [e for e in events if e.get("event_kind") == "dispatch"]
        self.assertEqual([(e["target_id"], e["mission_type"]) for e in dispatches], [("m1", "generic")])
        self.assertEqual(dispatches[0]["detail"]["目标"], SPAWN_PROMPT)
        worker_events = [e for e in events if e.get("agent_id") == "m1"]
        self.assertEqual([e["event_kind"] for e in worker_events],
                         ["request", "tool_call", "tool_result", "message", "status", "handoff"])
        self.assertIn("评审报告", worker_events[-1]["detail"]["主席收到的摘要"])
        speeches = [e for e in events if e.get("event_kind") == "message" and e.get("agent_id") == "chair"]
        self.assertTrue(any("报告已收齐" in e["message"] for e in speeches))

        # 子 agent 的报告作为工具结果回到主席上下文
        self.assertTrue(any("评审报告" in content for content in fake.tool_contents))

        # 装配：合同维度保留，缺维保守缺省 + 压 confidence
        a = raw["assessments"][0]
        self.assertEqual({d["key"] for d in a["dimensions"]}, {k for k, _l, _w in DIMENSIONS})
        by_key = {d["key"]: d for d in a["dimensions"]}
        self.assertEqual(by_key["direct_task_match"]["score"], 4.0)
        self.assertEqual(by_key["technical_depth"]["score"], 2.0)
        self.assertIn("维度 technical_depth 评估未覆盖", a["missing_information"])
        self.assertEqual(a["confidence"], 0.4)

        # 评分合同同构：能过确定性门槛并组装出最终输出
        state = {"prepared_resume": RESUME_DUMP, "prepared_jobs": [JOB.model_dump()], "job_fit_raw": raw}
        state.update(run_decision_guard(state))
        state.update(run_job_fit_formatter(state))
        self.assertEqual(state["final_output"]["interview_decision"], "hold")
        self.assertEqual(state["final_output"]["best_fit_jd_id"], "jd1")

    def test_worker_cannot_spawn_sub_agents(self) -> None:
        ctx, _ = _mk_ctx()
        fake = FakePanelLLM(
            chair_script=[], worker_script=[
                {"text": "", "tool_calls": [
                    {"id": "w1", "name": "spawn_agent",
                     "arguments": json.dumps({"goal": "嵌套", "prompt": "再派一个"})}],
                 },
                {"text": "放弃嵌套，直接交报告。", "tool_calls": []},
            ],
            contract=_contract(),
        )
        with patch(f"{LLM}.call_llm_tools", side_effect=fake):
            _events, outcome = _consume(run_agent_mission(
                "m9", "核查论文", SPAWN_PROMPT, {"resume": RESUME_DUMP, "files": [], "jobs": []}, ctx))
        self.assertEqual(outcome["status"], "done")
        self.assertIn("不能派生", "".join(fake.tool_contents))
        # 工具集层面也没有 spawn：提示词 + 硬拦双保险
        self.assertNotIn("spawn_agent", {t["function"]["name"] for t in WORKER_TOOLS})

    def test_spawn_budget_exhaustion_denies_new_spawns(self) -> None:
        ctx, _ = _mk_ctx()
        fake = FakePanelLLM(
            chair_script=[_spawn_call(), {"text": "预算已尽，基于已有信息收尾。", "tool_calls": []}],
            worker_script=[],
            contract=_contract(),
        )
        with patch.dict(os.environ, {"PANEL_MAX_SPAWNS": "0"}), \
             patch(f"{LLM}.call_llm_tools", side_effect=fake):
            events, _raw = _consume(run_panel_stream(RESUME_DUMP, [JOB], None, ctx))
        self.assertFalse(any(e.get("event_kind") == "dispatch" for e in events))
        self.assertTrue(any("预算已用尽" in content for content in fake.tool_contents))

    def test_invalid_contract_degrades_to_conservative_defaults(self) -> None:
        ctx, _ = _mk_ctx()
        fake = FakePanelLLM(
            chair_script=[{"text": "收工。", "tool_calls": []}],
            worker_script=[],
            contract={"assessments": []},
        )
        with patch(f"{LLM}.call_llm_tools", side_effect=fake):
            _events, raw = _consume(run_panel_stream(RESUME_DUMP, [JOB], None, ctx))
        self.assertEqual(fake.final_calls, 3)  # 校验失败重试穷尽
        a = raw["assessments"][0]
        self.assertTrue(all(d["score"] == 2.0 for d in a["dimensions"]))
        self.assertIn("主 agent 未产出评分合同", a["missing_information"])
        self.assertEqual(a["confidence"], 0.25)

    def test_complete_contract_passes_through_unchanged(self) -> None:
        full_dims = [{"key": key, "score": 3, "rationale": "证据充分支撑该维判断", "evidence": []}
                     for key, _label, _weight in DIMENSIONS]
        contract = _contract(dimensions=full_dims)
        raw = assemble([JOB], contract)
        a = raw["assessments"][0]
        self.assertTrue(all(d["score"] == 3 for d in a["dimensions"]))
        self.assertEqual(a["confidence"], 0.8)
        self.assertNotIn("主 agent 未产出评分合同", a["missing_information"])


class DossierTests(unittest.TestCase):
    def test_dossier_probes_text_layer(self) -> None:
        ctx, _ = _mk_ctx()
        dossier = build_dossier(RESUME_DUMP, [JOB], {"verified": 1}, ctx)
        self.assertTrue(dossier["files"][0]["text_layer"])
        self.assertEqual(dossier["jobs"][0]["jd_id"], "jd1")
        self.assertIn("三年 LLM 经验", dossier["jobs"][0]["raw_excerpt"])


if __name__ == "__main__":
    unittest.main()

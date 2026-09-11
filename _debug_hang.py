import faulthandler
import sys
import threading

sys.path.insert(0, ".")
from tests.test_interview_admission_evaluator import (  # noqa: E402
    InterviewAdmissionEvaluatorTests,
    evaluate_candidate_for_job,
    _quote_for,
)

case = InterviewAdmissionEvaluatorTests("test_full_workflow_repairs_via_continuation_and_keeps_audit")
case.setUp()

f = open("hang_dump.txt", "w", encoding="utf-8")
faulthandler.dump_traceback_later(15, exit=False, file=f)


class Fake:
    def call_llm_tools(self, messages, tools, **kwargs):
        last = [m for m in messages if m["role"] == "user"][-1]["content"]
        if tools:
            for tid in ("agent_system", "evaluation_loop", "research_transfer"):
                if "评估核心任务" in last and _quote_for.__self__ if False else False:
                    pass
            # 路由：spawn prompt 含任务标题
            for tid in ("agent_system", "evaluation_loop", "research_transfer"):
                if _quote_for(tid) and f"评估核心任务" in last:
                    from tests.test_interview_admission_evaluator import _title_for
                    if _title_for(tid) in last:
                        if tid == "evaluation_loop":
                            return {"text": "先核对简历中评测平台原文。", "tool_calls": []}
                        return {"text": "先核对简历中对应项目的原文。", "tool_calls": []}
            if "续命指令" in last:
                return {"text": "已剔除坏引用，重新给出评分。", "tool_calls": []}
            return {"text": "先核对简历原文。", "tool_calls": []}
        # JSON 通道
        import json
        for tid in ("agent_system", "evaluation_loop", "research_transfer"):
            from tests.test_interview_admission_evaluator import _score_response
            if f'"task_id":"{tid}"' in last:
                if tid == "evaluation_loop" and "评测数据闭环" in json.dumps(messages[-1], ensure_ascii=False) and False:
                    pass
                from tests.test_interview_admission_evaluator import _score_response as sr
                seg = sr(tid, 2, "大规模评测平台")
                return {"text": json.dumps(seg, ensure_ascii=False)}
        raise AssertionError("unexpected json call: " + last[-120:])


review = {
    "corrections": [],
    "interview_focus": [],
    "summary": "总审无异议",
}

# 直接替换 fake：按消息里的任务标题路由，evaluation_loop 第一次终稿用坏引用
state = {"evaluation_loop_final": 0}


class Fake2:
    def call_llm_tools(self, messages, tools, **kwargs):
        import json
        last = [m for m in messages if m["role"] == "user"][-1]["content"]
        if tools:
            for tid, title in (("agent_system", "Agent 系统研发"),
                               ("evaluation_loop", "评测与数据闭环"),
                               ("research_transfer", "研究成果迁移")):
                if "评估核心任务" in last and title in last:
                    if tid == "evaluation_loop":
                        return {"text": "先核对简历中评测平台原文。", "tool_calls": []}
                    return {"text": "先核对简历中对应项目的原文。", "tool_calls": []}
            if "续命指令" in last:
                return {"text": "已剔除坏引用并复核。", "tool_calls": []}
            return {"text": "先核对简历原文。", "tool_calls": []}
        if "重新只输出一个 JSON" in last or "评分 JSON（格式见系统提示）" in last or "输出一个 JSON 对象" in last:
            for tid in ("agent_system", "evaluation_loop", "research_transfer"):
                if f'"task_id":"{tid}"' in last:
                    from tests.test_interview_admission_evaluator import _score_response
                    if tid == "evaluation_loop":
                        state["evaluation_loop_final"] += 1
                        if state["evaluation_loop_final"] == 1:
                            bad = _score_response(tid, 2, "模型凭空生成的评测结果")
                            return {"text": json.dumps(bad, ensure_ascii=False)}
                        good = _score_response(tid, 2, "大规模评测平台")
                        return {"text": json.dumps(good, ensure_ascii=False)}
                    return {"text": json.dumps(_score_response(tid, 3, _quote_for(tid)), ensure_ascii=False)}
        return {"text": "继续。", "tool_calls": []}


with __import__("unittest").mock.patch(
        "agi_talent_radar.core.llm_client.call_llm_tools", side_effect=Fake2().call_llm_tools), \
     __import__("unittest").mock.patch(
        "agi_talent_radar.core.llm_client.call_llm_json",
        return_value={"corrections": [], "interview_focus": [], "summary": "总审无异议"}):
    result = evaluate_candidate_for_job(case.resume, "jd-agent", case.card)

print("DONE", result.decision)
faulthandler.cancel_dump_traceback_later()

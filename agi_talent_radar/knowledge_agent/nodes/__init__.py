"""人才知识 Agent 的 LangGraph 节点。

8 个节点按计划 §阶段 5：
    intent_parser → identity_resolver → local_retriever → tool_planner
        → external_investigator → evidence_normalizer → fact_persister
        → answer_composer
"""

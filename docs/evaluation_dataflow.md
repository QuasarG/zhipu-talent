# 简历评估全链路数据流（截至 2026-08 现状）

入口：`run_candidate_stream(resume)`（workbench 评估线程/SSE）。State = `TalentState`（TypedDict），
每个节点读若干字段、写若干字段。LLM 调用统一走 `call_llm_json` / `call_llm_tools`。

## 0. 导入阶段（评估前，异步）
- PDF → `extract_pdf_text`（PyMuPDF 文本层，扫描页 RapidOCR 兜底）→ raw_text
- LLM 结构化 → `CandidateResume`（education/experiences/projects/publications/skills）
- 论文外部核验（academic_check 已前移到这里的异步任务）：自述论文逐篇查 OpenAlex/AMiner，
  产出 `academic_report`（alignments: 已发表/未找到/冲突 + warnings），存 `CandidateORM.academic_report`

## 1. normalizer（LLM，temp=0）
- 读：`resume`
- 做：规则猜学校/机构档位 → LLM 裁定（NormalizerOutput）→ **脱敏**：education_blind /
  experiences_blind（校名→层级档位），重建 raw_text（脱敏版）
- 写：`normalized`（含 raw/blind 双份，raw 不外泄给后续评分节点）

## 2. academic_check（图内仍存在，编目已隐藏）
- 读：`resume.publications`
- 写：`academic_report`（导入阶段已算好则直接用）

## 3. evidence_extractor（LLM，temp=0.1）
- 读：`normalized`（不含 education_raw/experiences_raw）、`academic_report`、
  COMMON_RUBRIC + TRACK_SPECS（rubric 只含"看什么"的 evidence_rule）
- 写：`evidence[]`（e001…：dimension / quote / strength 1-5 /
  has_metric / has_specific_tool / has_ownership / track_hints）
- 校验：`quote_integrity_flags`——quote 必须能在 raw_text 里定位到（防幻觉证据）

## 4. track_router → route_auditor（LLM + 确定性校验）
- 读：`evidence`
- 写：`track_assignments[]`（track / weight / confidence / evidence_ids）、`routing_confidence`
- auditor：第二、三 Track 必须 ≥2 条独立证据，否则砍掉、权重还给主 Track

## 5. common_scorer（LLM，temp=0.1）
- 读：COMMON_RUBRIC、`evidence`、`stage_profile`、`academic_report`、resume_brief
- prompt 里有 0-5 分的一句话档位描述 + 硬性锚点（无验证封顶 2.5、缺组合证据封顶 3.5）
- 写：`common_scores[]`（6 维 × 0-5 → 加权 ≤40）、`common_score`

## 6. common_critic（无 LLM，确定性）
- 按规则压分：无证据引用 → ≤1；rigor/credibility 无验证 → ≤2.5；≥4 无组合证据 → ≤3.5
- portfolio floors：强证据组合触发时给各维度保底
- 写：校准后的 `common_scores` / `common_score`、`common_critic_flags`

## 7. *_track × 6（LLM，temp=0.1，并行）
- 读：该 Track 的 spec（维度/权重/高分规则）+ 过滤后的 Track 证据
- 写：`track_results[]`（每 Track：dimension_scores、raw_score、calibrated_score ≤60）

## 8. portfolio_aggregator（确定性）
- overall = common_score(≤40) + Σ track_weight × calibrated_score(≤60)，取整
- 写：`portfolio_assessment`

## 9. global_critic（确定性）：只产出一致性 flags，不改分

## 10. formatter（LLM，temp=0.2）
- 读：全部前述产物
- 写：`final_output` = CandidateEvaluation（overall_score、one_liner、core_strengths、
  potential_risks、interview_questions、cultivation_direction、recommended_tracks…）
- 落库：`save_evaluation` → EvaluationORM + evaluation_evidence 行

## 锚定现状裁决
- 已有：维度级"看什么"（evidence_rule）+ 0-5 一句话档位 + 硬性封顶（2.5/3.5，critic 强制执行）
+ quote 可追溯校验
- 没有：每档的行为锚点实例（用你们自己的真实简历标定"4 分长这样"）。
  所以"锚定好了"只对了一半：方向锚定了，刻度没锚定。

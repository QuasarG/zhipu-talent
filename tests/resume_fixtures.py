from __future__ import annotations

from agi_talent_radar.core.models import CandidateResume, ResumeProject


def make_resume_fixtures() -> list[CandidateResume]:
    return [
        CandidateResume(
            id="test_agent",
            name="Agent 测试候选人",
            target_role="Coding Agent 研究员",
            stage="博士在读",
            education=["985 高校计算机博士，GPA 3.82"],
            directions=["LLM Agent", "系统评测"],
            projects=[
                ResumeProject(
                    name="Coding Agent 闭环",
                    details=["负责设计工具调用、错误归因和自动验证工作流，修复率提升 18%"],
                ),
                ResumeProject(
                    name="SWE 评测平台",
                    details=["构建 Docker 沙箱和 Playwright 回归测试，支持失败恢复"],
                ),
            ],
            publications=["Agent 评测方法在投"],
            skills=["Python", "PyTorch", "Docker", "Playwright", "Agent"],
            screening_tags=["强工程闭环"],
        ),
        CandidateResume(
            id="test_multimodal",
            name="多模态测试候选人",
            target_role="多模态安全研究员",
            stage="博士在读",
            education=["计算机视觉博士"],
            directions=["多模态理解", "内容安全"],
            projects=[
                ResumeProject(
                    name="多模态风险评测",
                    details=["提出图文一致性基线并设计对照实验，覆盖 300+ 风险样例"],
                ),
                ResumeProject(
                    name="VLM 数据合成",
                    details=["构建可追溯数据过滤与人工复核流程"],
                ),
            ],
            skills=["Python", "PyTorch", "CLIP", "OpenCV"],
            screening_tags=["多模态安全"],
        ),
        CandidateResume(
            id="test_base",
            name="基模测试候选人",
            target_role="大模型基础研究员",
            stage="博士在读",
            education=["人工智能博士"],
            directions=["长上下文", "低精度训练"],
            projects=[
                ResumeProject(
                    name="长上下文建模",
                    details=["设计 attention baseline 与 ablation，吞吐提升 22%"],
                ),
                ResumeProject(
                    name="FP8 训练",
                    details=["维护 Triton 算子和数值稳定性回归测试"],
                ),
            ],
            skills=["Python", "PyTorch", "CUDA", "Triton"],
            screening_tags=["基模与系统"],
        ),
    ]

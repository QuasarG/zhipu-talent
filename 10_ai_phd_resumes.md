# 10份虚拟博士简历素材

说明：以下内容为人才筛选助手 Agent 测试用虚拟简历。姓名、联系方式、导师、论文题目、项目名均为合成内容；仅参考博士简历的结构、研究表达方式与能力标签，不对应真实个人。

---

## 候选人 01｜高效注意力与长上下文语言模型

**求职意向**：大模型预训练算法研究员 / 高效推理与长上下文方向  
**当前阶段**：博士一年级  
**教育背景**：  
- 2025.09 - 至今，某重点研究院，模式识别与智能系统，博士  
- 2021.09 - 2025.06，某 985 高校，人工智能，本科，GPA 3.82/4.0，专业排名前 5%

**研究方向**：线性注意力、稀疏注意力、状态空间记忆、长序列建模、Triton Kernel 优化。

**科研经历**：  
- **低秩衰减线性注意力机制研究**：针对线性注意力在长上下文检索任务中状态表达能力不足的问题，提出分块低秩衰减矩阵，将时间衰减、局部窗口和全局记忆统一到同一状态更新框架中。在 4B 参数语言模型上完成预训练消融，长上下文检索准确率提升 6.8%。  
- **面向长文档推理的动态记忆激活机制**：设计 token-level gate，使模型在不同层选择性激活外部记忆槽，降低无效状态写入。负责训练流水线、LM-Eval 评测、Needle-in-a-Haystack 测试与 ablation 分析。  
- **Flash Linear Attention 算子实现**：使用 Triton 实现分块并行扫描和反向传播 kernel，在 128K 上下文长度下显存占用降低约 35%，吞吐提升约 1.4 倍。

**代表成果**：  
- Efficient Decay Memory for Long-Context Language Models，拟投 NeurIPS 2026，一作  
- Dynamic Memory Activation for Linear Attention，Under Review，一作  
- 维护内部长上下文评测脚本，覆盖检索、代码理解、数学证明和多轮对话四类任务

**技能关键词**：PyTorch, Triton, TorchTitan, Transformers, vLLM, LM-Eval, CUDA 基础, 长上下文评测。

---

## 候选人 02｜多模态几何推理与可验证数据合成

**求职意向**：多模态推理算法研究员 / 数据合成 Agent 方向  
**当前阶段**：联合培养博士生  
**教育背景**：  
- 2026.09 - 至今，某人工智能研究院，博士，模式识别与智能系统  
- 2022.09 - 2026.06，某双一流高校，自动化，本科，综合排名 1/50

**研究方向**：多模态数学推理、几何图谱、可验证数据合成、Agentic Data Generation。

**科研经历**：  
- **可验证几何数据合成框架 GeoSynth-Agent**：设计“构图-出题-求解-验证-反思”的多智能体闭环系统，用结构化几何图谱表达点、线、角、圆、相似与全等等约束，并自动转译为可执行解析几何方程。  
- **混合式几何求解器**：结合符号求解、数值采样和逻辑一致性检查，对生成题目进行多层认证；在内部样本池中自动拦截约 47% 的错误题目，并通过反思重构修复其中 60% 以上。  
- **多模态训练数据质量评估**：构建图像、题干、证明链、答案四元一致性指标，用于筛选 VLM 数学训练数据。负责 benchmark 设计、模型评测和错误类型归因。

**代表成果**：  
- GeoSynth-Agent: Verifiable Geometry Data Generation with Multi-Agent Reasoning，拟投 ICML 2026，一作  
- Task-Aware Verification for Multimodal Math Reasoning Data，内部技术报告，一作  
- 构建覆盖 300+ 几何概念的合成数据原型库

**技能关键词**：Python, SymPy, PyTorch, multimodal LLM, data engine, verifier, prompt engineering, benchmark design。

---

## 候选人 03｜LLM 路由、协作与测试时扩展

**求职意向**：大模型 Agent 研究员 / 模型路由与协作方向  
**当前阶段**：博士在读  
**教育背景**：  
- 2024.09 - 至今，某创新型大学，计算机科学，博士  
- 2021.09 - 2024.06，某信息类高校，计算机技术，硕士，GPA 92/100  
- 2017.09 - 2021.06，某信息类高校，通信工程，本科

**研究方向**：LLM routing、multi-agent collaboration、test-time scaling、成本-效果联合优化。

**科研经历**：  
- **隐式成本偏好的 LLM 路由框架**：针对不同模型在任务能力、延迟、价格上的差异，提出基于元学习的路由器，从历史调用结果中学习“质量-成本”偏好，在开放问答、代码修复和 GUI 操作任务上降低 28% 调用成本。  
- **面向 GUI Agent 的分步路由机制**：将复杂任务拆解为感知、规划、执行、验证四类步骤，并为每步选择不同能力模型；相比单模型 Agent，任务成功率提升 9.5%。  
- **小模型协作推理**：改进 sampling-voting 框架，引入置信度校准和错误互补性约束，使多个 4B 以下模型在封闭式推理题上接近中型模型表现。

**代表成果**：  
- Cost-Aware Meta Routing for Large Language Models，Under Review，一作  
- Stepwise Model Routing for GUI Agents，Under Review，一作  
- 参与开源高性能算法工具库，修复评测指标与并行调度问题

**技能关键词**：PyTorch, Transformers, vLLM, Ray, Docker, Kubernetes, Python, routing policy, evaluation pipeline。

---

## 候选人 04｜多模态安全、讽刺理解与内容风险评估

**求职意向**：多模态安全算法研究员 / 内容理解与评测方向  
**当前阶段**：博士候选人  
**教育背景**：  
- 2025.09 - 至今，某重点高校，人工智能，博士  
- 2022.09 - 2025.06，某信息类高校，人工智能，硕士，GPA 91/100，IELTS 7.5  
- 2018.09 - 2022.06，某信息类高校，电子信息，本科

**研究方向**：多模态内容安全、meme harmfulness、讽刺目标识别、鲁棒评测与 RL scaling。

**科研经历**：  
- **上下文感知的多模态危害评测平台**：构建面向 meme、短视频截图和新闻配图的风险理解 benchmark，引入文化背景、隐喻目标和群体指向性标签，自动生成多视角评估报告。  
- **粗到细的多模态讽刺目标识别**：提出先定位候选目标、再判断语义反转关系的两阶段范式，结合 LMM 解释链和轻量分类头，在低资源场景下提升 F1 约 5%。  
- **安全模型在线误报分析**：在内容推荐实习中参与预排序模型与安全过滤联调，分析误杀、漏召和长尾风险样本，提出数据重采样与 hard negative mining 策略。

**代表成果**：  
- Context-Aware Harmfulness Evaluation for Multimodal Models，拟投 ACL 2026，一作  
- Coarse-to-Fine Sarcasm Target Identification with LMMs，已接收 CCF-A 会议，二作  
- 内部内容安全评测集覆盖 12 类风险、8 类语义反转现象

**技能关键词**：PyTorch, CLIP, LLaVA, Qwen-VL, data annotation, safety evaluation, recommendation model, OOD detection。

---

## 候选人 05｜3D 场景重建与多模态目标检测

**求职意向**：计算机视觉研究员 / 3D 重建与多模态感知方向  
**当前阶段**：直博二年级  
**教育背景**：  
- 2024.09 - 至今，某航空航天类高校，人工智能，博士  
- 2020.09 - 2024.06，某航空航天类高校，物理学，本科，排名前 10%  
- 2021.09 - 2024.06，辅修数学与应用数学

**研究方向**：RGB-Infrared 目标检测、Mamba 视觉模型、Gaussian Splatting、城市级三维重建。

**科研经历**：  
- **跨模态小样本目标检测**：提出基于状态空间模型的跨模态融合模块，分别建模 RGB 与红外图像的互补结构，在少样本目标检测基准上提升 mAP 4.2%。  
- **频域驱动的多模态检测框架**：使用小波分解提取低频语义与高频边缘信息，构建多频特征交互模块，提高夜间、遮挡和低照度场景鲁棒性。  
- **城市级 Gaussian Splatting 重建**：针对大场景重建中显存高、几何不准和分块边界伪影问题，设计深度-法向量双监督、空间自适应剪枝和无缝分块渲染流程。

**代表成果**：  
- Fusion State Space Models for Cross-Modality Object Detection，CCF-A 会议，一作  
- Scalable Gaussian Reconstruction for Urban Scenes，拟投 ICLR 2026，一作  
- 参与自动驾驶多传感器感知数据处理流水线开发

**技能关键词**：PyTorch, OpenCV, CUDA, Gaussian Splatting, Mamba, MMDetection, 3D vision, RGB-T detection。

---

## 候选人 06｜低精度训练、量化与大模型系统优化

**求职意向**：大模型系统算法研究员 / 训练推理优化方向  
**当前阶段**：博士研究生  
**教育背景**：  
- 2024.09 - 至今，某综合性大学，计算机科学与技术，博士  
- 2020.09 - 2024.06，某交通类高校，人工智能，本科，拔尖班

**研究方向**：FP8/FP4 训练、量化感知训练、异常激活抑制、软硬协同优化。

**实习经历**：  
- **文档智能与高效 OCR 模型实习**：参与文档版面分析、公式识别和高分辨率文档解析模型训练，负责模型结构实验、训练脚本维护和评测集扩展。  
- **低精度基础模型训练框架**：在研究院项目中负责 FP8 训练稳定性验证，分析 Transformer 激活值 outlier 对量化误差和训练崩溃的影响。

**项目经历**：  
- **Transformer 激活异常值消除机制**：提出基于通道重参数化与归一化前移的结构改造，在语言模型和视觉 Transformer 上同时降低 outlier 频率，使 FP8 训练更稳定。  
- **通用快速 QAT 框架**：设计激活优先的量化校准策略，减少传统 QAT 的长周期微调成本，在多个 ViT 任务上达到接近全精度性能。  
- **高分辨率文档解析 VLM**：参与解耦式视觉语言模型训练，在公式、表格、密集文本页面上优化 patch 选择和多尺度识别。

**代表成果**：  
- Transformers without Extreme Activations for FP8 Training，拟投 CVPR 2026，一作  
- Practical Lightning QAT for Vision Transformers，已接收 NeurIPS 2025，一作  
- 参与开源文档解析工具，负责公式识别模块

**技能关键词**：PyTorch, DeepSpeed, Megatron, CUDA, quantization, FP8, TensorRT, OCR, VLM training。

---

## 候选人 07｜Coding Agent、SWE Bench 与 AI Scientist

**求职意向**：Agent 研究员 / 软件工程智能体方向  
**当前阶段**：硕博连读博士一年级  
**教育背景**：  
- 2025.09 - 至今，某综合性大学，人工智能，博士  
- 2023.09 - 2025.06，某综合性大学，人工智能，硕士  
- 2019.09 - 2023.06，某综合性大学，软件工程，本科，GPA 92/100

**研究方向**：Coding Agent、issue resolving、环境配置、实验自动化、AI Scientist。

**科研经历**：  
- **多语言 Issue 修复基准构建**：参与构建覆盖 Python、Java、JavaScript、TypeScript、Go、C++ 的软件修复数据集，负责仓库筛选、失败测试复现、patch 验证和数据清洗。  
- **视觉信息增强的软件修复 Agent**：提出将 UI 截图、报错截图和运行结果图像纳入 issue 理解流程，通过多模态上下文检索提升前端 bug 修复成功率。  
- **社科论文可复现性判断 Agent**：设计多智能体系统，自动完成论文解析、代码环境配置、依赖安装、结果运行与图表一致性检查，支持 R、Stata、Python 项目。

**代表成果**：  
- Visual Context Helps Issue Resolving，ACL Findings，一作  
- PaperRepro-Agent: Automated Computational Reproducibility Assessment，Under Review，一作  
- 参与多语言 SWE benchmark，合著论文拟投 NeurIPS

**工程经历**：  
- 开发基于 Flask/Vue 的实验管理平台，支持任务队列、日志回放、产物对比和失败归因。  
- 熟悉 Docker、Conda、CI、Playwright、GitHub Actions 与常见软件项目构建流程。

**技能关键词**：Python, Java, TypeScript, Docker, Playwright, Git, SWE-bench, Claude Code, multi-agent system。

---

## 候选人 08｜人-Agent 协同平台与具身智能

**求职意向**：Agent 平台研发研究员 / 多智能体系统方向  
**当前阶段**：直博一年级  
**教育背景**：  
- 2025.09 - 至今，某 985 高校，计算机科学，博士  
- 2021.09 - 2025.06，某综合性大学，数学与应用数学，本科，GPA 3.7/4.0

**研究方向**：Human-Agent Collaboration、多智能体通信拓扑、具身智能、图形化工作流。

**项目经历**：  
- **大规模人-Agent 协同工作平台**：设计面向混合组织的通信与任务管理系统，使 Agent 拥有独立身份、上下文记忆、任务订阅和自动汇报能力。负责后端架构、sandbox 集群和事件总线设计。  
- **图形化 Spec-Driven Development 工具**：探索“规格文档作为唯一事实来源”的软件开发范式，将需求、测试、实现、评审和部署节点串成可视化 Agent 工作流。  
- **具身智能代码解释器框架**：复现视觉语言模型、代码解释器和机器人仿真环境的三端交互流程，在 Omniverse 场景中实现语言指令到机器人动作的闭环执行。

**科研经历**：  
- **多 Agent 通信拓扑优化**：将 Agent 间消息交换建模为有约束图优化问题，研究集中式、层级式和市场式协作结构对任务完成率和 token 成本的影响。  
- **价值偏好驱动的群体决策模型**：基于 LLM 抽取价值卡片，并用图匹配方法生成协商方案，用于社区议题模拟。

**代表成果**：  
- Hybrid Human-Agent Organizations: Communication, Memory and Coordination，技术报告，一作  
- 获国际数学建模竞赛特等奖级别奖项，队长  
- 维护个人开源项目，累计 star 200+

**技能关键词**：Python, Rust, Node.js, React, FastAPI, Docker, sandbox, multi-agent, Omniverse, optimization。

---

## 候选人 09｜文档解析、OCR 与高分辨率 VLM

**求职意向**：文档智能算法研究员 / 多模态应用方向  
**当前阶段**：博士研究生  
**教育背景**：  
- 2024.09 - 至今，某重点大学，计算机科学与技术，博士  
- 2020.09 - 2024.06，某理工类高校，人工智能，本科，排名前 3%

**研究方向**：文档版面分析、数学公式识别、OCR-VLM、高分辨率图像理解。

**实习经历**：  
- **开放文档智能平台实习**：负责复杂 PDF、论文、教材、财报等场景的版面分析模型迭代，优化文本块、表格、公式、图片和页眉页脚的结构化抽取。  
- **公式识别模型研发**：参与通用公式识别网络设计，改进区域选择注意力机制，在手写、扫描、拍照和排版公式混合数据上提升准确率。

**项目经历**：  
- **鲁棒文档布局分析模型**：通过多样化文档合成和感知增强，提升模型对长表格、双栏论文、脚注、嵌套公式和低清扫描件的泛化能力。  
- **解耦式高分辨率文档 VLM**：将全页粗读、局部精读和结构化输出解耦，减少高分辨率输入带来的 token 冗余。负责训练数据过滤、prompt 模板、评测指标和错误分析。  
- **长尾视觉语义一致性增强**：设计面向 OCR 与医学图像的 montage augmentation，使模型在难例少样本场景下保持更稳定的识别与解释。

**代表成果**：  
- Robust Layout Analysis through Diverse Document Synthesis，Under Review，共同一作  
- Universal Mathematical Expression Recognition Network，拟投 CVPR，一作  
- 参与文档解析开源项目，负责评测脚本和错误归因面板

**技能关键词**：PyTorch, PaddleOCR, LayoutLM, Donut, Qwen-VL, PDF parsing, OCR, synthetic data, evaluation。

---

## 候选人 10｜AI4Science、强化学习与生物医学多模态

**求职意向**：AI4Science 研究员 / 生物医学多模态与强化学习方向  
**当前阶段**：博士在读  
**教育背景**：  
- 2024.09 - 至今，某研究型大学，人工智能，博士  
- 2021.09 - 2024.06，某医学交叉学院，生物医学工程，硕士  
- 2017.09 - 2021.06，某综合性大学，计算机科学，本科

**研究方向**：医学 VLM、单细胞建模、强化学习推理优化、跨模态持续学习。

**科研经历**：  
- **医学多任务大模型适配**：面向慢病管理、医学问答和影像报告生成，构建领域指令数据并进行 SFT、知识蒸馏和 RAG 增强，在内部医学咨询任务上显著降低幻觉率。  
- **单细胞身份与表达联合建模**：探索离散扩散模型用于细胞类型、基因表达和扰动响应的联合预测，提升低覆盖测序场景下的稳定性。  
- **低成本 VLM 强化学习训练**：设计可验证奖励与 curriculum sampling 策略，在几何推理、医学图像问答和实验设计任务上提升小规模 VLM 的推理一致性。  
- **跨模态持续学习**：提出谱正则化约束视觉-语言交叉注意力漂移，降低新任务训练对旧任务能力的遗忘。

**代表成果**：  
- Data-Free Continual Learning for Multimodal LLMs，拟投 CVPR 2026，一作  
- Masked Discrete Diffusion for Single-Cell Identity and Expression，拟投 ICML，三作  
- Medical RAG with Verifiable Evidence Chains，内部项目负责人

**技能关键词**：PyTorch, Hugging Face, RLHF/RLVR, medical VLM, RAG, single-cell modeling, scikit-learn, data governance。


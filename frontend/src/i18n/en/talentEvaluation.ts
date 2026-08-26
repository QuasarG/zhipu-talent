// 统一"人才评估"外壳（/talent-evaluation）文案。中文即 key，这里提供英文翻译。
export default {
  // 外壳与工具栏
  "人才评估": "Talent Evaluation",
  "面试准入": "Interview Admission",
  "面试准入：判断候选人是否值得进入某个岗位的面试": "Admission: decide whether a candidate is worth interviewing for a specific role",
  "新建准入评估": "New Admission Assessment",
  "返回浏览": "Back to Browsing",
  "停止失败": "Failed to stop",
  "评估批次": "Assessment Batch",

  // 左侧候选人文件夹
  "搜索姓名、方向或岗位": "Search name, direction, or role",
  "还没有候选人文件夹": "No candidate folders yet",
  "导入简历后，每个候选人会作为一个文件夹出现在这里": "After import, each candidate appears here as a folder",
  "折叠": "Collapse",
  "展开": "Expand",
  "暂无岗位评估": "No role assessments yet",
  "未命名岗位": "Unnamed role",
  "未评估": "Not assessed",

  // 导入运行恢复提示
  "上次导入可能仍在后台进行": "A previous import may still be running in the background",
  "完成的简历会自动出现在候选人列表中": "Completed resumes will appear in the candidate list automatically",
  "刷新列表": "Refresh list",
  "知道了": "Got it",

  // 面试准入内容区
  "从左侧选择一个候选人": "Select a candidate on the left",
  "选中候选人根节点查看简历；选择岗位子项查看该配对的准入报告": "Select a candidate folder to view the resume, or a role item for its admission report",
  "选择左侧文件夹中的岗位子项": "Select a role item in a candidate folder",
  "每个岗位子项对应一次候选人–JD 准入评估，进入或不进入面试都保留完整报告": "Each role item is one candidate–JD admission assessment; full reports are kept whether or not the candidate advances",
  "该配对还没有当前报告": "No current report for this pair",
  "可以在此配对上发起准入评估，或等待正在运行的评估完成": "Start an admission assessment for this pair, or wait for the running one to finish",
  "报告与节点": "Report & Nodes",
  "运行过程": "Run Trace",

  // 新建批次（临时选择模式）
  "选择一批候选人和岗位，提交前确认配对数量；这是临时选择模式，不改变左侧文件夹": "Pick a set of candidates and roles, confirm the pair count before submitting. This temporary mode does not change the folder layout",
  "退出选择": "Exit selection",

  // 报告正文
  "报告已失效，需要重评": "Report invalidated, reassessment required",
  "/100 加权总分": "/100 weighted total",
  "首要任务等级 ≥ 2": "Primary tasks at level ≥ 2",
  "加权总分 ≥ 50": "Weighted total ≥ 50",
  "总分计算明细": "Score Breakdown",
  "Σ(单项 × 系数) ÷ Σ系数": "Σ(item × weight) ÷ Σweights",
  "首要": "Primary",
  "主要": "Major",
  "补充": "Supporting",
  "迁移边界": "Transfer Boundary",
  "能力缺口": "Capability Gaps",
  "针对性面试重点": "Targeted Interview Focus",
  "模型与降级": "Models & Fallback",
  "{n} 次节点降级": "{n} node fallbacks",
} as Record<string, string>;

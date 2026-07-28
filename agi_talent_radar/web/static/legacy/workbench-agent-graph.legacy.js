window.AgentGraph = (() => {
  const NODE_LABELS = {
    normalizer: "脱敏与标准化",
    evidence_extractor: "深度证据挖掘",
    track_router: "多 Track 路由",
    route_auditor: "Track 路由校验",
    common_scorer: "通用潜力打分",
    common_critic: "通用潜力校准",
    base_track: "Base 基模 Track",
    agent_track: "Agent Track",
    safety_track: "大模型安全 Track",
    multimodal_track: "多模态 Track",
    systems_track: "系统优化 Track",
    ai4science_track: "AI4Science Track",
    portfolio_aggregator: "跨 Track 加权汇总",
    global_critic: "全局一致性复核",
    formatter: "结构化组装",
  };

  const STAGES = [
    {
      key: "preparation",
      label: "预处理",
      description: "统一信息并建立可追溯证据",
      nodes: ["normalizer", "evidence_extractor"],
    },
    {
      key: "routing",
      label: "Track 路由",
      description: "确定专业方向、权重和置信度",
      nodes: ["track_router", "route_auditor"],
    },
    {
      key: "parallel",
      label: "并行评估",
      description: "通用潜力与各专业 Track 同步评估",
      parallel: true,
      lanes: [
        { key: "common", label: "通用潜力链", nodes: ["common_scorer", "common_critic"], common: true },
        { key: "base", label: "Base", nodes: ["base_track"] },
        { key: "agent", label: "Agent", nodes: ["agent_track"] },
        { key: "safety", label: "Safety", nodes: ["safety_track"] },
        { key: "multimodal", label: "Multimodal", nodes: ["multimodal_track"] },
        { key: "systems", label: "Systems", nodes: ["systems_track"] },
        { key: "ai4science", label: "AI4Science", nodes: ["ai4science_track"] },
      ],
      nodes: [
        "common_scorer",
        "common_critic",
        "base_track",
        "agent_track",
        "safety_track",
        "multimodal_track",
        "systems_track",
        "ai4science_track",
      ],
    },
    {
      key: "aggregation",
      label: "汇总复核",
      description: "加权合并、全局校验并生成面谈结论",
      nodes: ["portfolio_aggregator", "global_critic", "formatter"],
    },
  ];

  const NODE_ORDER = STAGES.flatMap((stage) => stage.nodes);
  const TRACK_NODES = [
    "base_track",
    "agent_track",
    "safety_track",
    "multimodal_track",
    "systems_track",
    "ai4science_track",
  ];
  const PARALLEL_TERMINALS = ["common_critic", ...TRACK_NODES];
  const TERMINAL_STATUSES = new Set(["done", "skipped", "error"]);

  function createNodeRows(initialStatus = "pending", initialMessage = "等待执行…") {
    return new Map(NODE_ORDER.map((nodeKey) => [nodeKey, {
      label: NODE_LABELS[nodeKey],
      message: initialMessage,
      status: initialStatus,
    }]));
  }

  function setNodeStatus(rows, nodeKey, status, message = "") {
    const row = rows.get(nodeKey) || { label: NODE_LABELS[nodeKey] || nodeKey };
    row.status = status;
    if (message) row.message = message;
    rows.set(nodeKey, row);
  }

  function advanceAfterEvent(rows, nodeKey) {
    const nextByNode = {
      normalizer: "evidence_extractor",
      evidence_extractor: "track_router",
      track_router: "route_auditor",
      common_scorer: "common_critic",
      portfolio_aggregator: "global_critic",
      global_critic: "formatter",
    };
    const nextNode = nextByNode[nodeKey];
    if (nextNode) activateNode(rows, nextNode);

    if (nodeKey === "route_auditor") {
      activateNode(rows, "common_scorer");
      TRACK_NODES.forEach((trackNode) => activateNode(rows, trackNode));
    }

    const branchesFinished = PARALLEL_TERMINALS.every((key) => {
      const status = rows.get(key)?.status;
      return TERMINAL_STATUSES.has(status);
    });
    if (branchesFinished) activateNode(rows, "portfolio_aggregator");
  }

  function activateNode(rows, nodeKey) {
    const row = rows.get(nodeKey);
    if (!row || row.status !== "pending") return;
    row.status = "running";
    row.message = "正在执行…";
  }

  function statusLabel(status) {
    const labels = {
      queued: "排队",
      pending: "等待",
      running: "运行中",
      done: "完成",
      skipped: "未命中",
      error: "失败",
    };
    return labels[status] || status;
  }

  return {
    NODE_LABELS,
    NODE_ORDER,
    STAGES,
    TRACK_NODES,
    createNodeRows,
    setNodeStatus,
    advanceAfterEvent,
    statusLabel,
  };
})();

import assert from "node:assert/strict";
import test from "node:test";

import { markdownHeadings } from "../src/features/chat/chatNavigationModel.ts";

test("extracts level 1-3 markdown headings with stable ids", () => {
  assert.deepEqual(
    markdownHeadings("# 总结\n正文\n## 经历\n### 风险\n#### 不进入目录", "m1-0"),
    [
      { id: "m1-0-heading-0", label: "总结", level: 1 },
      { id: "m1-0-heading-1", label: "经历", level: 2 },
      { id: "m1-0-heading-2", label: "风险", level: 3 },
    ],
  );
});

test("strips common inline markdown from outline labels", () => {
  assert.deepEqual(
    markdownHeadings("## **能力**与[证据](https://example.test) ##", "m2-1"),
    [{ id: "m2-1-heading-0", label: "能力与证据", level: 2 }],
  );
});

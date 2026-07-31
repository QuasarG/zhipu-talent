import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveTrackWeightPercent,
  tokenizeEvidenceReferences,
} from "../src/features/resume/scoreOverviewModel.ts";

test("falls back to the routed assignment weight when the recommendation weight is zero", () => {
  assert.equal(resolveTrackWeightPercent(0, 0.95), 95);
});

test("normalizes fractional and percentage track weights", () => {
  assert.equal(resolveTrackWeightPercent(0.4), 40);
  assert.equal(resolveTrackWeightPercent(40), 40);
});

test("extracts evidence ids from dimension rationale text", () => {
  const parts = tokenizeEvidenceReferences("候选人发表论文（e005, e006），并负责项目 e011。", new Set(["e005", "e006", "e011"]));
  assert.deepEqual(
    parts.filter((part) => part.kind === "evidence").map((part) => part.evidenceId),
    ["e005", "e006", "e011"],
  );
});

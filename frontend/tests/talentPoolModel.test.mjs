import assert from "node:assert/strict";
import test from "node:test";

import {
  dominantTrack,
  transitionEngagementSelection,
  validVisibleSelection,
  visibleTalentGroupKeys,
} from "../src/features/pool/talentPoolModel.ts";

test("uses the highest weighted evaluated track", () => {
  assert.equal(dominantTrack([
    { track: "agent", weight: 0.3529 },
    { track: "safety", weight: 0.6471 },
  ]), "safety");
});

test("requires two deliberate clicks before committing an HR status", () => {
  const first = transitionEngagementSelection("newly_admitted", null, "contacted");
  assert.deepEqual(first, { pending: "contacted", commit: null });

  const second = transitionEngagementSelection("newly_admitted", first.pending, "contacted");
  assert.deepEqual(second, { pending: null, commit: "contacted" });
});

test("clicking another HR status moves the pending confirmation", () => {
  assert.deepEqual(
    transitionEngagementSelection("newly_admitted", "contacted", "interviewing"),
    { pending: "interviewing", commit: null },
  );
});

test("clears the selection when filters remove it from the visible result", () => {
  assert.equal(validVisibleSelection("person-2", ["person-1", "person-3"]), null);
});

test("preserves a selection that remains visible", () => {
  assert.equal(validVisibleSelection("person-2", ["person-1", "person-2"]), "person-2");
});

test("keeps the empty state stable when there are no visible results", () => {
  assert.equal(validVisibleSelection(null, []), null);
  assert.equal(validVisibleSelection("person-1", []), null);
});

test("hides zero-hit groups only while filters are active", () => {
  const counts = { ungrouped: 0, group_a: 2, group_b: 0 };
  assert.deepEqual(visibleTalentGroupKeys(counts, true), ["group_a"]);
  assert.deepEqual(visibleTalentGroupKeys(counts, false), ["ungrouped", "group_a", "group_b"]);
});

test("returns no group sections for a filtered zero-result list", () => {
  assert.deepEqual(visibleTalentGroupKeys({ ungrouped: 0, group_a: 0 }, true), []);
});

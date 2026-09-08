import { test } from 'node:test';
import assert from 'node:assert/strict';
import { activeAgents, admissionActivities, panelActivities } from '../src/features/admission/agentActivityModel.ts';

test('tool identities survive normalization so the shared tool renderer can pair results', () => {
  const [event] = panelActivities([{ node: 'panel_lead', status: 'running', message: '读取材料', agent_id: 'm1', agent_type: 'deep_read', event_kind: 'tool_call', tool: 'read_text', call_id: 'read-1' }]);
  assert.equal(event.tool, 'read_text');
  assert.equal(event.callId, 'read-1');
});

test('parallel scorers remain active independently and terminal runs clear activity', () => {
  const events = ['a', 'b'].map(agent => ({ agent, role: 'task_scorer', status: 'running', kind: 'request' }));
  assert.equal(activeAgents(events, true).length, 2);
  events.push({ agent: 'a', role: 'task_scorer', status: 'completed', kind: 'handoff', target: 'system' });
  assert.deepEqual(activeAgents(events, true).map(e => e.agent), ['b']);
  assert.deepEqual(activeAgents(events, false), []);
});

test('dispatch is not fabricated worker execution and legacy events have no inferred recipient', () => {
  const events = panelActivities([{ node: 'panel_lead', status: 'running', message: '派工', agent_id: 'chair', agent_type: 'chair', target_id: 'm1', mission_id: 'm1', event_kind: 'dispatch' }]);
  assert.deepEqual(activeAgents(events, true), []);
  assert.equal(events[0].mission, null);
  const legacy = admissionActivities([{ node_id: 'capability_mapping', status: 'completed', summary: '完成' }]);
  assert.equal(legacy[0].kind, 'legacy');
  assert.equal(legacy[0].target, undefined);
});

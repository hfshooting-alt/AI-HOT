import { test } from 'node:test';
import assert from 'node:assert/strict';
import { collectionLabel } from '../../app/_lib/display/collection.ts';

test('unstarted sources and stopped tasks have distinct labels', () => {
  assert.equal(collectionLabel({status:'failed',reasonCode:'not_started_budget'}),'费用熔断后未启动');
  assert.equal(collectionLabel({status:'failed',reasonCode:'budget_stopped'}),'费用止损');
  assert.equal(collectionLabel({status:'partial',reasonCode:'boundary_unverified'}),'部分完成：时间窗口未扫完');
  assert.equal(collectionLabel({status:'failed'}),'采集未完成，原因待核实');
});

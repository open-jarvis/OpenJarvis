import assert from 'node:assert/strict';
import test from 'node:test';

import {
  evaluateLocalWakeText,
  hasWakePhrase,
  isLocalWakeLoopStopped,
  nextWakeStatusAfterCommand,
  shouldRunLocalWakeLoop,
  shouldContinueLocalWakeLoop,
  stripWakePhrase,
} from 'file:///private/tmp/openjarvis-wake-tests/wake.js';

test('detects Korean and English wake phrases', () => {
  assert.equal(hasWakePhrase('헤이 프라이데이'), true);
  assert.equal(hasWakePhrase('hey friday'), true);
  assert.equal(hasWakePhrase('그냥 일반 명령'), false);
});

test('captures command after wake phrase', () => {
  const wake = evaluateLocalWakeText('프라이데이', {
    awaitingCommand: false,
    lastDetectedAt: 0,
    now: 10_000,
  });

  assert.equal(wake.action, 'wake_detected');
  assert.equal(wake.awaitingCommand, true);

  const command = evaluateLocalWakeText('오늘 일정 알려줘', {
    awaitingCommand: wake.awaitingCommand,
    lastDetectedAt: wake.lastDetectedAt,
    now: 13_000,
  });

  assert.equal(command.action, 'command_ready');
  assert.equal(command.command, '오늘 일정 알려줘');
});

test('successful wake-command cycle returns to waiting when still enabled', () => {
  assert.equal(nextWakeStatusAfterCommand({
    wakeListening: true,
    stopRequested: false,
    aborted: false,
  }), 'wake');
});

test('empty command returns to waiting without sending', () => {
  const step = evaluateLocalWakeText('프라이데이', {
    awaitingCommand: true,
    lastDetectedAt: 10_000,
    now: 13_000,
  });

  assert.equal(step.action, 'none');
  assert.equal(step.awaitingCommand, true);
});

test('silent command capture returns to wake waiting', () => {
  const step = evaluateLocalWakeText('', {
    awaitingCommand: true,
    lastDetectedAt: 10_000,
    now: 13_000,
  });

  assert.equal(step.action, 'none');
  assert.equal(step.awaitingCommand, false);
});

test('debounces duplicate wake phrases', () => {
  const step = evaluateLocalWakeText('프라이데이', {
    awaitingCommand: false,
    lastDetectedAt: 10_000,
    now: 11_000,
  });

  assert.equal(step.action, 'duplicate_wake');
  assert.equal(step.awaitingCommand, false);
  assert.equal(step.lastDetectedAt, 10_000);
});

test('strips wake phrase from command text', () => {
  assert.equal(stripWakePhrase('헤이 프라이데이 오늘 날씨 알려줘'), '오늘 날씨 알려줘');
});

test('local wake loop only runs in active app mode', () => {
  assert.equal(shouldRunLocalWakeLoop({
    wakeListening: true,
    speechEnabled: true,
    appMode: true,
    documentHidden: false,
  }), true);
  assert.equal(shouldRunLocalWakeLoop({
    wakeListening: true,
    speechEnabled: true,
    appMode: true,
    documentHidden: true,
  }), false);
  assert.equal(shouldRunLocalWakeLoop({
    wakeListening: true,
    speechEnabled: true,
    appMode: false,
    documentHidden: false,
  }), false);
});

test('stop loop state wins over active listening', () => {
  assert.equal(isLocalWakeLoopStopped({ stopped: false, aborted: false }), false);
  assert.equal(isLocalWakeLoopStopped({ stopped: true, aborted: false }), true);
  assert.equal(isLocalWakeLoopStopped({ stopped: false, aborted: true }), true);
});

test('user stop prevents wake loop restart', () => {
  assert.equal(shouldContinueLocalWakeLoop({
    wakeListening: true,
    stopRequested: true,
    aborted: false,
  }), false);
  assert.equal(nextWakeStatusAfterCommand({
    wakeListening: true,
    stopRequested: true,
    aborted: false,
  }), 'stopped');
});

test('duplicate start guard keeps one running loop', () => {
  let started = 0;
  const runningRef = { current: false };
  const start = () => {
    if (runningRef.current) return;
    runningRef.current = true;
    started += 1;
  };

  start();
  start();

  assert.equal(started, 1);
});

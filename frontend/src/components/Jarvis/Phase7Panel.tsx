import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  activateCanonicalSkill,
  createMutationContext,
  decideSkillPromotion,
  deprecateCanonicalSkill,
  fetchCandidateHistory,
  fetchCanonicalSkills,
  fetchLearningCandidates,
  fetchLearningConflicts,
  fetchLearningEvaluations,
  fetchLearningHealth,
  fetchRoutingRecommendations,
  fetchTaskFeedback,
  recordTaskFeedback,
  rejectLearningCandidate,
  requestSkillPromotion,
  resolveLearningConflict,
  reviewLearningCandidate,
  reviseTaskFeedback,
  revokeTaskFeedback,
  rollbackCanonicalSkill,
  testCanonicalSkill,
} from '../../lib/api';
import type {
  CandidateHistoryInfo,
  FeedbackRecordInfo,
  LearningCandidateInfo,
  LearningConflictInfo,
  LearningHealth,
  RoutingRecommendationView,
  SkillDetailInfo,
  SkillVersionView,
  TaskFeedbackInfo,
  TraceEvaluationInfo,
} from '../../lib/api';

type PanelMode = 'learning' | 'skills';
type Decision = 'allow_once' | 'deny';

type DialogAction =
  | { kind: 'candidate-review'; candidate: LearningCandidateInfo }
  | { kind: 'candidate-reject'; candidate: LearningCandidateInfo }
  | { kind: 'conflict'; conflict: LearningConflictInfo }
  | { kind: 'skill-test'; skillId: string; value: SkillVersionView }
  | { kind: 'promotion-request'; skillId: string; value: SkillVersionView }
  | { kind: 'deprecate'; skillId: string; value: SkillVersionView }
  | { kind: 'promotion-decision'; skillId: string; value: SkillVersionView; decision: Decision }
  | { kind: 'activate'; skillId: string; value: SkillVersionView; decision: Decision }
  | { kind: 'rollback'; skillId: string; value: SkillVersionView; targetVersion: string; decision: Decision }
  | { kind: 'feedback-create' }
  | { kind: 'feedback-revise'; feedback: FeedbackRecordInfo }
  | { kind: 'feedback-revoke'; feedback: FeedbackRecordInfo };

const actor = 'jarvis-ui-user';

function short(value: string | null | undefined, size = 12): string {
  if (!value) return 'none';
  return value.length > size ? `${value.slice(0, size)}…` : value;
}

function recordValue(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value)
    : 'none';
}

function evidenceIds(candidate: LearningCandidateInfo): string[] {
  return candidate.source_evidence_ids.length
    ? candidate.source_evidence_ids
    : [candidate.candidate_id];
}

function versionEvidence(value: SkillVersionView): string[] {
  return [value.version.candidate_id];
}

function outcomeDistribution(evaluations: TraceEvaluationInfo[]): string {
  const counts = evaluations.reduce<Record<string, number>>((result, evaluation) => {
    result[evaluation.evaluation_class] = (result[evaluation.evaluation_class] || 0) + 1;
    return result;
  }, {});
  return Object.entries(counts).map(([name, count]) => `${name}: ${count}`).join(' · ') || 'No evaluations';
}

export function Phase7DecisionDialog({
  title,
  decision,
  busy,
  onConfirm,
  onClose,
}: {
  title: string;
  decision?: Decision;
  busy: boolean;
  onConfirm: (reason: string, feedbackType: string, conflictDecision: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('Reviewed in the Jarvis UI');
  const [feedbackType, setFeedbackType] = useState('helpful');
  const [conflictDecision, setConflictDecision] = useState('keep_both_scoped');
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="phase7-dialog-title" className="hud-panel p-4" dir="auto">
      <h3 id="phase7-dialog-title" className="font-semibold">{title}</h3>
      {title.includes('Feedback') && (
        <label className="mt-3 block text-xs">
          Feedback type
          <select value={feedbackType} onChange={(event) => setFeedbackType(event.target.value)} className="mt-1 w-full rounded-lg p-2" style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }}>
            {['correct', 'incorrect', 'partially_correct', 'helpful', 'not_helpful', 'action_succeeded', 'action_failed', 'correction', 'candidate_rejected', 'skill_suggested'].map((value) => <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>)}
          </select>
        </label>
      )}
      {title.includes('conflict') && (
        <label className="mt-3 block text-xs">
          Resolution
          <select value={conflictDecision} onChange={(event) => setConflictDecision(event.target.value)} className="mt-1 w-full rounded-lg p-2" style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }}>
            {['keep_both_scoped', 'reject_left', 'reject_right', 'supersede_left', 'supersede_right', 'unresolved'].map((value) => <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>)}
          </select>
        </label>
      )}
      <label className="mt-3 block text-xs">
        Reason or structured feedback
        <textarea dir="auto" rows={3} maxLength={256} value={reason} onChange={(event) => setReason(event.target.value)} className="mt-1 w-full rounded-lg p-2" style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-input-border)' }} />
      </label>
      {decision && (
        <p className="mt-2 text-xs" style={{ color: 'var(--color-warning)' }}>
          The selected action is explicit: <strong>{decision === 'allow_once' ? 'Apply now' : 'Reject'}</strong>. Text cannot change it.
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={busy || !reason.trim()} onClick={() => onConfirm(reason.trim(), feedbackType, conflictDecision)} className="rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-40" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
          Confirm {decision === 'allow_once' ? 'apply now' : decision === 'deny' ? 'reject' : 'action'}
        </button>
        <button type="button" disabled={busy} onClick={onClose} className="rounded-lg px-4 py-2 text-sm" style={{ border: '1px solid var(--color-border)' }}>Cancel</button>
      </div>
    </div>
  );
}

export function Phase7Panel({
  mode,
  taskId,
  sessionId,
  answerId,
  answerDigest,
  onChanged,
}: {
  mode: PanelMode;
  taskId: string | null;
  sessionId: string;
  answerId?: string | null;
  answerDigest?: string | null;
  onChanged?: () => void;
}) {
  const [health, setHealth] = useState<LearningHealth | null>(null);
  const [evaluations, setEvaluations] = useState<TraceEvaluationInfo[]>([]);
  const [candidates, setCandidates] = useState<LearningCandidateInfo[]>([]);
  const [histories, setHistories] = useState<Record<string, CandidateHistoryInfo>>({});
  const [conflicts, setConflicts] = useState<LearningConflictInfo[]>([]);
  const [routing, setRouting] = useState<RoutingRecommendationView[]>([]);
  const [feedback, setFeedback] = useState<TaskFeedbackInfo | null>(null);
  const [skills, setSkills] = useState<SkillDetailInfo[]>([]);
  const [dialog, setDialog] = useState<DialogAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      if (mode === 'learning') {
        const [nextHealth, nextEvaluations, nextCandidates, nextConflicts, nextRouting, nextFeedback] = await Promise.all([
          fetchLearningHealth(),
          fetchLearningEvaluations(),
          fetchLearningCandidates(),
          fetchLearningConflicts(),
          fetchRoutingRecommendations(taskId || undefined),
          taskId ? fetchTaskFeedback(taskId) : Promise.resolve(null),
        ]);
        const nextHistories = Object.fromEntries(await Promise.all(nextCandidates.map(async (candidate) => [candidate.candidate_id, await fetchCandidateHistory(candidate.candidate_id)] as const)));
        setHealth(nextHealth);
        setEvaluations(nextEvaluations);
        setCandidates(nextCandidates);
        setHistories(nextHistories);
        setConflicts(nextConflicts);
        setRouting(nextRouting);
        setFeedback(nextFeedback);
      } else {
        const [nextHealth, nextSkills] = await Promise.all([fetchLearningHealth(), fetchCanonicalSkills()]);
        setHealth(nextHealth);
        setSkills(nextSkills);
      }
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Phase-7 data could not be loaded.');
    }
  }, [mode, taskId]);

  useEffect(() => { void load(); }, [load]);

  const candidateById = useMemo(() => Object.fromEntries(candidates.map((candidate) => [candidate.candidate_id, candidate])), [candidates]);

  const runAction = async (reason: string, feedbackType: string, conflictDecision: string) => {
    if (!dialog || !taskId) return;
    setBusy(true);
    setError(null);
    const mutation = createMutationContext(`phase7-${dialog.kind}`);
    const commonTask = { task_id: taskId, session_id: sessionId, actor };
    const reasonCode = `ui_${dialog.kind.replace(/-/g, '_')}`;
    try {
      if (dialog.kind === 'candidate-review' || dialog.kind === 'candidate-reject') {
        const body = { ...commonTask, expected_revision: dialog.candidate.revision, reason, reason_code: reasonCode, evidence_reference_ids: evidenceIds(dialog.candidate) };
        if (dialog.kind === 'candidate-review') await reviewLearningCandidate(dialog.candidate.candidate_id, body, mutation);
        else await rejectLearningCandidate(dialog.candidate.candidate_id, body, mutation);
      } else if (dialog.kind === 'conflict') {
        const left = candidateById[dialog.conflict.candidate_ids[0]];
        const right = candidateById[dialog.conflict.candidate_ids[1]];
        if (!left || !right) throw new Error('Both conflict candidates must be loaded before resolution.');
        await resolveLearningConflict(dialog.conflict.conflict_id, {
          ...commonTask,
          candidate_ids: dialog.conflict.candidate_ids,
          candidate_revisions: [left.revision, right.revision],
          decision: conflictDecision,
          reason,
          reason_code: reasonCode,
          evidence_digests: [dialog.conflict.conflict_signature],
        }, mutation);
      } else if (dialog.kind === 'feedback-create') {
        if (!answerId || !answerDigest) throw new Error('Feedback requires a persisted answer and its digest.');
        await recordTaskFeedback(taskId, { session_id: sessionId, actor, answer_id: answerId, feedback_type: feedbackType, structured_content: { summary: reason }, source_digest: answerDigest, expected_revision: 0 }, mutation);
      } else if (dialog.kind === 'feedback-revise') {
        await reviseTaskFeedback(dialog.feedback.feedback_id, { ...commonTask, feedback_type: feedbackType, structured_content: { summary: reason }, expected_revision: dialog.feedback.revision }, mutation);
      } else if (dialog.kind === 'feedback-revoke') {
        await revokeTaskFeedback(dialog.feedback.feedback_id, { ...commonTask, expected_revision: dialog.feedback.revision }, mutation);
      } else if (dialog.kind === 'rollback') {
        const latest = [...dialog.value.activations].reverse()[0];
        await rollbackCanonicalSkill(dialog.skillId, {
          ...commonTask,
          scope_key: latest ? recordValue(latest, 'scope_key') : `task-${taskId}`,
          expected_scope_revision: latest ? Number(recordValue(latest, 'target_scope_revision')) : 1,
          current_semantic_version: dialog.value.version.semantic_version,
          target_semantic_version: dialog.targetVersion,
          decision: dialog.decision,
          reason_code: reasonCode,
          evidence_reference_ids: versionEvidence(dialog.value),
        }, mutation);
      } else {
        const value = dialog.value;
        const base = {
          ...commonTask,
          semantic_version: value.version.semantic_version,
          expected_candidate_revision: value.version.candidate_revision,
          expected_state_revision: value.head.state_revision,
          evidence_reference_ids: versionEvidence(value),
        };
        if (dialog.kind === 'skill-test') await testCanonicalSkill(dialog.skillId, base, mutation);
        if (dialog.kind === 'promotion-request') await requestSkillPromotion(dialog.skillId, { ...base, activation_intended: false, evidence_digests: [value.version.manifest_hash], reason_code: reasonCode }, mutation);
        if (dialog.kind === 'promotion-decision') {
          const pending = [...value.promotions].reverse().find((item) => recordValue(item, 'decision') === 'pending');
          if (!pending) throw new Error('No pending promotion request is available.');
          await decideSkillPromotion(dialog.skillId, { ...base, request_promotion_id: recordValue(pending, 'promotion_id'), decision: dialog.decision, evidence_digests: [value.version.manifest_hash], reason_code: reasonCode }, mutation);
        }
        if (dialog.kind === 'activate') {
          const latest = [...value.activations].reverse()[0];
          await activateCanonicalSkill(dialog.skillId, {
            ...base,
            scope_key: latest ? recordValue(latest, 'scope_key') : `task-${taskId}`,
            expected_scope_revision: latest ? Number(recordValue(latest, 'target_scope_revision')) : 0,
            expected_active_skill_id: latest ? recordValue(latest, 'skill_id') : null,
            expected_active_semantic_version: latest ? recordValue(latest, 'semantic_version') : null,
            decision: dialog.decision,
            reason_code: reasonCode,
          }, mutation);
        }
        if (dialog.kind === 'deprecate') {
          const latest = [...value.activations].reverse()[0];
          await deprecateCanonicalSkill(dialog.skillId, {
            ...base,
            scope_key: latest ? recordValue(latest, 'scope_key') : null,
            expected_scope_revision: latest ? Number(recordValue(latest, 'target_scope_revision')) : null,
            reason_code: reasonCode,
          }, mutation);
        }
      }
      setDialog(null);
      setNotice('The explicit Phase-7 action was recorded. No automatic promotion, activation, routing, or memory write occurred.');
      await load();
      onChanged?.();
    } catch (value) {
      setError(value instanceof Error ? value.message : 'The Phase-7 action failed.');
    } finally {
      setBusy(false);
    }
  };

  if (!taskId) {
    return <section className="hud-panel p-4" role="status"><h2 className="font-semibold">{mode === 'learning' ? 'Learning' : 'Skills'}</h2><p className="mt-2 text-sm">Select or create a canonical task before reviewing or changing Phase-7 records.</p></section>;
  }

  return (
    <section className="space-y-4" aria-label={mode === 'learning' ? 'Learning review workspace' : 'Skill lifecycle workspace'} dir="auto">
      {error && <div role="alert" className="rounded-xl p-3" style={{ border: '1px solid var(--color-error)', color: 'var(--color-error)' }}>{error}</div>}
      {notice && <div role="status" className="rounded-xl p-3 text-sm" style={{ border: '1px solid var(--color-success)' }}>{notice}</div>}
      {dialog && (
        <Phase7DecisionDialog
          title={dialog.kind.includes('feedback') ? 'Feedback action' : dialog.kind === 'conflict' ? 'Resolve conflict' : dialog.kind.replace(/-/g, ' ')}
          decision={'decision' in dialog ? dialog.decision : undefined}
          busy={busy}
          onConfirm={(reason, feedbackType, conflictDecision) => void runAction(reason, feedbackType, conflictDecision)}
          onClose={() => setDialog(null)}
        />
      )}

      <section className="hud-panel p-4" aria-labelledby="learning-health-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="learning-health-heading" className="font-semibold">Learning health</h2>
          <button type="button" onClick={() => void load()} className="rounded-lg px-3 py-2 text-xs" style={{ border: '1px solid var(--color-border)' }}>Refresh</button>
        </div>
        {!health ? <p className="mt-3 text-sm">Loading canonical health…</p> : (
          <dl className="mt-3 grid gap-x-4 gap-y-2 text-xs sm:grid-cols-[10rem_1fr_10rem_1fr]">
            <dt>Status</dt><dd>{health.status} · {health.store_status}</dd>
            <dt>Versions</dt><dd>{health.evaluator_version} · {health.extractor_version}</dd>
            <dt>Migrations</dt><dd>{health.migrations.map((item) => `${item.version}:${short(item.checksum)}`).join(', ')}</dd>
            <dt>Conflicts/quarantine</dt><dd>{health.open_conflicts} / {health.quarantined_candidates}</dd>
            <dt>Promotion/active</dt><dd>{health.promotion_pending} / {health.active_skill_versions}</dd>
            <dt>Verification/metrics</dt><dd>{health.last_verification || 'none'} / {health.last_metric_revision || 'none'}</dd>
            <dt>Shadow routing</dt><dd>{health.shadow_routing.shadow_mode ? 'on, shadow only' : 'invalid'} · {health.shadow_routing.recommendations}</dd>
            <dt>Feedback/recovery</dt><dd>{health.feedback_store.status} · {health.recovery_status}</dd>
            <dt>Integrity</dt><dd>{health.integrity_errors.join(', ') || 'no errors'}</dd>
          </dl>
        )}
      </section>

      {mode === 'learning' ? (
        <>
          <section className="hud-panel p-4" aria-labelledby="evaluations-heading">
            <h2 id="evaluations-heading" className="font-semibold">Evaluations and outcomes</h2>
            <p className="mt-2 text-xs">{outcomeDistribution(evaluations)}</p>
            <div className="mt-3 space-y-2">
              {evaluations.map((evaluation) => <article key={evaluation.evaluation_id} className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg-secondary)' }}><strong>{evaluation.task_type} · {evaluation.evaluation_class}</strong><p>Verification {evaluation.verification_state} · Evidence {evaluation.evidence_state} · Confidence {evaluation.confidence}</p><p>Provenance {evaluation.evaluator_version} · hash {short(evaluation.evaluation_hash)}</p><p>{evaluation.confidence_basis.join(' · ') || 'No confidence basis'}</p></article>)}
              {!evaluations.length && <p className="text-sm">No evaluations are stored.</p>}
            </div>
          </section>

          <section className="hud-panel p-4" aria-labelledby="candidates-heading">
            <h2 id="candidates-heading" className="font-semibold">Candidates, evidence, and review history</h2>
            <div className="mt-3 space-y-3">
              {candidates.map((candidate) => {
                const history = histories[candidate.candidate_id];
                return <article key={candidate.candidate_id} className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="flex flex-wrap justify-between gap-2"><strong>{candidate.title}</strong><span>rev {candidate.revision} · {candidate.state} · risk {candidate.risk_level}</span></div>
                  <dl className="mt-2 grid gap-x-3 gap-y-1 sm:grid-cols-[9rem_1fr]">
                    <dt>Provenance</dt><dd>{candidate.origin} · {candidate.project} · {candidate.scope}</dd>
                    <dt>Evidence</dt><dd>{candidate.source_evidence_ids.join(', ') || 'none'}</dd>
                    <dt>Independence</dt><dd>{candidate.independence_count} source(s)</dd>
                    <dt>Duplicate</dt><dd>{short(candidate.duplicate_signature)}</dd>
                    <dt>Conflict</dt><dd>{short(candidate.conflict_signature)}</dd>
                    <dt>Quarantine</dt><dd>{candidate.quarantine_reasons.join(', ') || 'none'}</dd>
                    <dt>Review history</dt><dd>{history ? `${history.revisions.length} revision(s), ${history.reviews.length} review event(s)` : 'loading'}</dd>
                    <dt>Tests/verification</dt><dd>{candidate.proposed_tests.join(', ') || 'none'} / {candidate.proposed_verification.join(', ') || 'none'}</dd>
                  </dl>
                  <details className="mt-2"><summary>Structured content and provenance</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify({ content: candidate.structured_content, provenance: candidate.provenance, history }, null, 2)}</pre></details>
                  <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => setDialog({ kind: 'candidate-review', candidate })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-border)' }}>Start review</button><button type="button" onClick={() => setDialog({ kind: 'candidate-reject', candidate })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-error)' }}>Reject candidate</button></div>
                </article>;
              })}
              {!candidates.length && <p className="text-sm">No learning candidates are stored.</p>}
            </div>
          </section>

          <section className="hud-panel p-4" aria-labelledby="conflicts-heading"><h2 id="conflicts-heading" className="font-semibold">Conflicts</h2><div className="mt-3 space-y-2">{conflicts.map((conflict) => <article key={conflict.conflict_id} className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg-secondary)' }}><strong>{conflict.conflict_type} · {conflict.priority}</strong><p>{conflict.reason}</p><p>{conflict.candidate_ids.join(' ↔ ')} · {conflict.is_open ? 'open' : 'resolved'}</p>{conflict.is_open && <button type="button" onClick={() => setDialog({ kind: 'conflict', conflict })} className="mt-2 rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-warning)' }}>Resolve conflict</button>}</article>)}{!conflicts.length && <p className="text-sm">No conflicts.</p>}</div></section>

          <section className="hud-panel p-4" aria-labelledby="routing-heading"><h2 id="routing-heading" className="font-semibold">Shadow routing comparison</h2><p className="mt-1 text-xs">Recommendations are evidence-only; the actual productive route remains authoritative.</p><div className="mt-3 space-y-2">{routing.map(({ recommendation, comparison }) => <article key={recommendation.recommendation_id} className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg-secondary)' }}><strong>{recommendation.recommended_route} (shadow only)</strong><p>Actual {recommendation.actual_route} · risk {recommendation.expected_risk} · confidence {recommendation.confidence}</p><p>Sample {recommendation.sample_size}{recommendation.small_sample ? ' · SMALL SAMPLE' : ''} · {recommendation.confidence_basis.join(', ')}</p><p>Comparison {comparison?.comparison_result || 'pending'} · limitations {recommendation.known_limitations.join(', ') || 'none'}</p></article>)}{!routing.length && <p className="text-sm">No shadow recommendation for this task.</p>}</div></section>

          <section className="hud-panel p-4" aria-labelledby="feedback-heading"><div className="flex flex-wrap justify-between gap-2"><h2 id="feedback-heading" className="font-semibold">Revisioned feedback history</h2><button type="button" disabled={!answerId || !answerDigest} onClick={() => setDialog({ kind: 'feedback-create' })} className="rounded-lg px-3 py-2 text-xs disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>Record feedback</button></div><div className="mt-3 space-y-2">{feedback?.feedback.map((item) => <article key={`${item.feedback_id}-${item.revision}`} className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg-secondary)' }}><strong>{item.feedback_type} · rev {item.revision}{item.revoked_at ? ' · revoked' : ''}</strong><p>Answer/execution {item.answer_id || item.execution_id} · source {short(item.source_digest)}</p><p dir="auto">{JSON.stringify(item.structured_content)}</p><div className="mt-2 flex gap-2"><button type="button" disabled={Boolean(item.revoked_at)} onClick={() => setDialog({ kind: 'feedback-revise', feedback: item })} className="rounded-lg px-3 py-2 disabled:opacity-40" style={{ border: '1px solid var(--color-border)' }}>Revise</button><button type="button" disabled={Boolean(item.revoked_at)} onClick={() => setDialog({ kind: 'feedback-revoke', feedback: item })} className="rounded-lg px-3 py-2 disabled:opacity-40" style={{ border: '1px solid var(--color-error)' }}>Revoke</button></div></article>)}{!feedback?.feedback.length && <p className="text-sm">No explicit feedback. Silence is not approval.</p>}</div></section>
        </>
      ) : (
        <section className="hud-panel p-4" aria-labelledby="skills-heading">
          <h2 id="skills-heading" className="font-semibold">Verified skill lifecycle</h2>
          <p className="mt-1 text-xs">Only explicit, revision-bound actions are available. There is no automatic promotion, activation, or learned production routing.</p>
          <div className="mt-3 space-y-4">
            {skills.flatMap((skill) => skill.versions.map((value, index) => {
              const pending = value.promotions.some((item) => recordValue(item, 'decision') === 'pending');
              const target = skill.versions.find((candidate) => candidate.version.semantic_version !== value.version.semantic_version)?.version.semantic_version;
              return <article key={`${skill.skill_id}-${value.version.semantic_version}`} className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg-secondary)' }}>
                <div className="flex flex-wrap justify-between gap-2"><strong>{skill.skill_id} · {value.version.semantic_version}</strong><span>{value.head.lifecycle_state} · state rev {value.head.state_revision}</span></div>
                <dl className="mt-2 grid gap-x-3 gap-y-1 sm:grid-cols-[10rem_1fr]">
                  <dt>Active scope</dt><dd>{value.activations.map((item) => `${recordValue(item, 'scope_key')}@${recordValue(item, 'target_scope_revision')}`).join(', ') || 'not active'}</dd>
                  <dt>Candidate origin</dt><dd>{value.manifest.origin_candidate_id}@{value.manifest.origin_candidate_revision}</dd>
                  <dt>Manifest hash</dt><dd>{short(value.version.manifest_hash, 20)}</dd>
                  <dt>Tools/capabilities</dt><dd>{value.manifest.allowed_tool_ids.join(', ') || 'none'} / {value.manifest.required_capabilities.join(', ') || 'none'}</dd>
                  <dt>Risk</dt><dd>{value.manifest.maximum_risk_level}</dd>
                  <dt>Tests/verification</dt><dd>{value.verification.length} run(s) · latest {value.verification.length ? recordValue(value.verification[value.verification.length - 1], 'status') : 'none'}</dd>
                  <dt>Promotion</dt><dd>{pending ? 'PENDING explicit decision' : `${value.promotions.length} record(s)`}</dd>
                  <dt>Executions/pins</dt><dd>{value.executions.length} canonical pinned record(s)</dd>
                  <dt>Metrics</dt><dd>{value.metrics.length} revision(s){value.metrics.length && Number(recordValue(value.metrics[value.metrics.length - 1], 'sample_size')) < 5 ? ' · SMALL SAMPLE' : ''}</dd>
                  <dt>Deprecation</dt><dd>{value.manifest.deprecated_at || `${value.deprecations.length} record(s)`}</dd>
                  <dt>Rollback</dt><dd>{value.rollbacks.length} record(s)</dd>
                  <dt>Limitations</dt><dd>{value.manifest.known_limitations.join(', ') || 'none declared'}</dd>
                  <dt>Quarantined imports</dt><dd>{value.quarantined_imports.length}</dd>
                </dl>
                <details className="mt-2"><summary>Verification, metrics, executions, and history</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap">{JSON.stringify({ verification: value.verification, metrics: value.metrics, executions: value.executions, promotions: value.promotions, activations: value.activations, deprecations: value.deprecations, rollbacks: value.rollbacks, quarantinedImports: value.quarantined_imports }, null, 2)}</pre></details>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" onClick={() => setDialog({ kind: 'skill-test', skillId: skill.skill_id, value })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-border)' }}>Start tests</button>
                  <button type="button" onClick={() => setDialog({ kind: 'promotion-request', skillId: skill.skill_id, value })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-border)' }}>Request promotion</button>
                  {pending && <><button type="button" onClick={() => setDialog({ kind: 'promotion-decision', skillId: skill.skill_id, value, decision: 'allow_once' })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-warning)' }}>Promotion allow once</button><button type="button" onClick={() => setDialog({ kind: 'promotion-decision', skillId: skill.skill_id, value, decision: 'deny' })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-error)' }}>Promotion deny</button></>}
                  <button type="button" onClick={() => setDialog({ kind: 'activate', skillId: skill.skill_id, value, decision: 'allow_once' })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-warning)' }}>Activation allow once</button>
                  <button type="button" onClick={() => setDialog({ kind: 'activate', skillId: skill.skill_id, value, decision: 'deny' })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-error)' }}>Activation deny</button>
                  <button type="button" onClick={() => setDialog({ kind: 'deprecate', skillId: skill.skill_id, value })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-error)' }}>Deprecate</button>
                  {target && <><button type="button" onClick={() => setDialog({ kind: 'rollback', skillId: skill.skill_id, value, targetVersion: target, decision: 'allow_once' })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-warning)' }}>Rollback allow once</button><button type="button" onClick={() => setDialog({ kind: 'rollback', skillId: skill.skill_id, value, targetVersion: target, decision: 'deny' })} className="rounded-lg px-3 py-2" style={{ border: '1px solid var(--color-error)' }}>Rollback deny</button></>}
                </div>
                {index === 0 && value.packages.length > 0 && <p className="mt-2">Local metadata packages: {value.packages.length}; imports remain quarantined.</p>}
              </article>;
            }))}
            {!skills.length && <p className="text-sm">No canonical skills are registered.</p>}
          </div>
        </section>
      )}
    </section>
  );
}

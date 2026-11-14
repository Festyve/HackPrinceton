import { useContext, useEffect, useRef } from "react";
import type { CaseView, RawView } from "./api";
import type { Run } from "./model";
import { Chips, EvidenceCtx } from "./common";
import { Dialog } from "./dialog";
import { useRecordedPlayback, PlaybackControls } from "./playback";
import { useRecordedTrace } from "./trace-api";
import type { TraceSpan } from "./trace-api";
import { RawViewer } from "./evidence";

export interface RawState {
  loading: boolean;
  error: string | null;
  data: RawView | null;
  eventId?: string;
}
export function EvidenceInspector({
  raw,
  onClose,
}: {
  raw: RawState;
  onClose: () => void;
}) {
  const trigger = useRef<HTMLElement | null>(null);
  const close = useRef(onClose);
  const closeButton = useRef<HTMLButtonElement>(null);
  close.current = onClose;
  useEffect(() => {
    trigger.current = document.activeElement as HTMLElement;
    closeButton.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close.current();
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      if (trigger.current?.isConnected) trigger.current.focus();
    };
  }, []);
  return (
    <aside
      className="evidence-inspector"
      aria-label="Evidence inspector"
      data-testid="evidence-inspector"
    >
      <header>
        <div>
          <p className="eyebrow">Evidence inspector</p>
          <h2>Go back to the source.</h2>
        </div>
        <button
          ref={closeButton}
          onClick={onClose}
          aria-label="Close evidence inspector"
        >
          ×
        </button>
      </header>
      <p className="small muted">
        Read-only source bytes. Scroll the record horizontally; Escape returns
        to your finding.
      </p>
      <RawViewer raw={raw} />
    </aside>
  );
}

export function InvestigationTools({
  onSources,
  onPlan,
  onCaseFile,
  onTrace,
  onQuestions,
  hasCase,
  planProgress,
}: {
  onSources: () => void;
  onPlan: () => void;
  onCaseFile: () => void;
  onTrace: () => void;
  onQuestions: () => void;
  hasCase: boolean;
  planProgress?: string;
}) {
  return (
    <div
      className="investigation-tools"
      role="toolbar"
      aria-label="Investigation tools"
    >
      <span className="tool-section-label">Inspect</span>
      <button data-testid="btn-sources" onClick={onSources} disabled={!hasCase}>
        Sources & witnesses
      </button>
      <button onClick={onPlan} disabled={!hasCase} aria-label="Plan">
        Plan{" "}
        {planProgress && (
          <span className="tool-plan-progress">{planProgress}</span>
        )}
      </button>
      <button onClick={onCaseFile} disabled={!hasCase}>
        Case file
      </button>
      <button onClick={onTrace} disabled={!hasCase}>
        Trace
      </button>
      <button onClick={onQuestions} disabled={!hasCase}>
        Questions <span aria-hidden="true">↙</span>
      </button>
    </div>
  );
}

/** A compact summary of recorded tasks; the full history stays one click away. */
export function PlanSummary({ run, onOpen }: { run: Run; onOpen: () => void }) {
  if (!run.todo.length) return null;
  const current =
    run.todo.find((t) => t.status === "in_progress") ??
    run.todo.find((t) => t.status !== "completed");
  const completed = run.todo.filter((t) => t.status === "completed").length;
  return (
    <button
      className="plan-summary"
      onClick={onOpen}
      aria-label="Open recorded investigation plan"
    >
      <span className="eyebrow">
        Recorded plan · {completed}/{run.todo.length} completed
      </span>
      <span>{current?.text ?? "All recorded tasks completed"}</span>
      <span aria-hidden="true">↗</span>
    </button>
  );
}

export function PlanView({ run, caseId }: { run: Run; caseId: string }) {
  const { trace, error } = useRecordedTrace(caseId, run.lastSeq);
  return (
    <section className="plan-view" data-testid="investigation-plan">
      <p className="small muted">
        Tasks and status come from the actual investigation trace. Nothing
        completes just because time has passed.
      </p>
      {!run.todo.length ? (
        <p>No plan event has been received for this run.</p>
      ) : (
        <ol className="task-list">
          {run.todo.map((t, i) => (
            <li key={`${i}-${t.text}`} data-status={t.status}>
              <span className="task-marker" aria-hidden="true">
                {t.status === "completed"
                  ? "✓"
                  : t.status === "in_progress"
                    ? "◉"
                    : "○"}
              </span>
              <div>
                <b>{t.text}</b>
                <small>{t.status.replace(/_/g, " ")}</small>
              </div>
            </li>
          ))}
        </ol>
      )}
      {run.planHistory.length > 1 && (
        <details className="plan-history">
          <summary>
            Recorded plan updates ({run.planHistory.length - 1})
          </summary>
          {run.planHistory.slice(1).map((entry, i) => {
            const previous = run.planHistory[i].items;
            const changed = entry.items.filter(
              (t) =>
                !previous.some(
                  (p) => p.text === t.text && p.status === t.status,
                ),
            );
            return (
              <section key={entry.seq}>
                <h4>Trace event {entry.seq}</h4>
                <ul>
                  {changed.map((t, n) => (
                    <li key={n}>
                      {t.text} · {t.status.replace(/_/g, " ")}
                    </li>
                  ))}
                </ul>
                {entry.evidence_ids.length ? (
                  <Chips ids={entry.evidence_ids} />
                ) : (
                  <p className="small muted">
                    No triggering evidence reference was supplied with this plan
                    update.
                  </p>
                )}
              </section>
            );
          })}
        </details>
      )}
      {trace && (
        <section
          className="recorded-revisions"
          data-testid="recorded-plan-revisions"
        >
          <h3>Changes to the plan’s content</h3>
          {!trace.behaviors.plan_revisions.length && (
            <p>
              No content revision was recorded. Status updates alone are not a
              revised plan.
            </p>
          )}
          {trace.behaviors.plan_revisions.map((revision) => {
            const preceding = trace.spans.find(
              (span) => span.start_seq === revision.after?.seq,
            );
            return (
              <article key={revision.seq}>
                <h4>Plan event {revision.seq}</h4>
                {revision.added.map((text) => (
                  <p key={`add-${text}`}>
                    <span className="ok">Added:</span> {text}
                  </p>
                ))}
                {revision.removed.map((text) => (
                  <p key={`remove-${text}`}>
                    <span className="amber">Removed:</span> {text}
                  </p>
                ))}
                {revision.after && (
                  <p className="small muted">
                    Recorded after event {revision.after.seq}:{" "}
                    {revision.after.what}. {revision.after.summary}
                  </p>
                )}
                <Chips ids={preceding?.evidence_ids} />
              </article>
            );
          })}
          <p className="small muted">
            “After” is recorded order, not proof of a cause or a reconstruction
            of model thoughts.
          </p>
        </section>
      )}
      {error && (
        <p className="small amber">
          The structured trace could not be read: {error}. Received plan events
          remain visible above.
        </p>
      )}
    </section>
  );
}

export function TraceView({ run, caseId }: { run: Run; caseId: string }) {
  const { trace, error } = useRecordedTrace(caseId, run.lastSeq);
  const spans: TraceSpan[] =
    trace?.spans ??
    run.tools.map((t) => ({
      span_id: `t${t.seq}`,
      parent_id: null,
      kind: "tool",
      actor: t.agent,
      tool: t.tool,
      arguments: t.args,
      result_summary: t.result_summary,
      evidence_ids: t.evidence_ids,
      status: t.ok ? "ok" : "error",
      start_seq: t.seq,
      start: "",
      ms: t.ms,
    }));
  const playback = useRecordedPlayback(spans.length);
  function depth(span: TraceSpan) {
    let level = 0,
      parent = span.parent_id;
    const seen = new Set<string>();
    while (parent && !seen.has(parent)) {
      seen.add(parent);
      level += 1;
      parent = spans.find((s) => s.span_id === parent)?.parent_id ?? null;
    }
    return Math.min(level, 3);
  }
  return (
    <section className="trace-view" data-testid="investigation-trace">
      <p className="small muted">
        {trace?.note ??
          "Actual received tool events. Model thoughts are not exposed or reconstructed."}
      </p>
      {error && (
        <p className="small amber">
          Structured trace unavailable: {error}. Received tool records remain
          visible.
        </p>
      )}
      <PlaybackControls playback={playback} />
      {!spans.length && (
        <p>No tool calls or delegated spans have been recorded.</p>
      )}
      <ol className="trace-events">
        {spans.slice(0, playback.shown).map((span) => (
          <li
            key={span.span_id}
            data-kind={span.kind}
            data-parent={span.parent_id ?? ""}
            style={{ marginLeft: depth(span) * 16 }}
          >
            <details>
              <summary>
                <span className="trace-seq mono">{span.start_seq}</span>
                <span>
                  <b>
                    {span.tool
                      ? span.tool.replace(/_/g, " ")
                      : span.kind === "run"
                        ? "Investigation run"
                        : "Delegated evidence review"}
                  </b>
                  <small>
                    {span.actor} · {span.kind}
                  </small>
                </span>
                <span
                  className={
                    span.status === "error"
                      ? "bad"
                      : span.status === "running"
                        ? "amber"
                        : "ok"
                  }
                >
                  {span.status === "ok" ? "Completed" : span.status}
                  {span.ms != null ? ` · ${span.ms} ms` : ""}
                </span>
              </summary>
              <dl className="facts">
                <dt>Recorded span</dt>
                <dd className="mono">
                  {span.span_id}
                  {span.parent_id ? ` · parent ${span.parent_id}` : " · root"}
                </dd>
                {span.tool && (
                  <>
                    <dt>Tool ID</dt>
                    <dd className="mono">{span.tool}</dd>
                  </>
                )}
                <dt>Actor</dt>
                <dd>{span.actor}</dd>
                {span.start && (
                  <>
                    <dt>Recorded time</dt>
                    <dd>
                      {span.start}
                      {span.end ? ` → ${span.end}` : ""}
                    </dd>
                  </>
                )}
                <dt>Input / task</dt>
                <dd>
                  <pre>
                    {span.arguments == null
                      ? (span.task ?? "No input summary recorded")
                      : typeof span.arguments === "string"
                        ? span.arguments
                        : JSON.stringify(span.arguments, null, 2)}
                  </pre>
                </dd>
                <dt>Result</dt>
                <dd>{span.result_summary || "No result summary recorded"}</dd>
              </dl>
              <Chips ids={span.evidence_ids} />
            </details>
          </li>
        ))}
      </ol>
      <p className="small muted">
        Nesting comes from recorded parent span IDs. Display order remains the
        recorded sequence. Per-span cost and tokens were not supplied; aggregate
        measured use is in Details.
      </p>
    </section>
  );
}

export function CaseFile({ view, run }: { view: CaseView; run: Run }) {
  const open = useContext(EvidenceCtx);
  const { trace, error } = useRecordedTrace(view.case.case_id, run.lastSeq);
  return (
    <section className="case-file" data-testid="case-file">
      <p className="eyebrow">Investigator case file</p>
      <h3>{view.card?.title ?? view.case.title}</h3>
      <p>
        {view.report?.summary || "A report summary has not been recorded yet."}
      </p>
      <p className="small muted">
        Recorded file-write previews, which may be truncated. These are not a
        reconstruction of hidden reasoning.
      </p>
      {trace && (
        <div className="case-file-history" data-testid="case-file-history">
          <h3>Filesystem activity</h3>
          <p>
            {trace.behaviors.case_file.writes} writes / edits ·{" "}
            {trace.behaviors.case_file.reads_after_a_write} later reads of
            written files · {trace.behaviors.resumed.times} recorded resumes
          </p>
          <ol>
            {trace.case_file.map((file) => (
              <li key={file.seq}>
                <b>{file.op}</b> <span className="mono">{file.path}</span>
                <small>
                  Event {file.seq} · {file.t}
                </small>
              </li>
            ))}
          </ol>
        </div>
      )}
      {error && (
        <p className="small amber">Filesystem trace unavailable: {error}</p>
      )}
      {run.notes.length ? (
        run.notes.map((n, i) => (
          <section key={i}>
            <h4>{n.path}</h4>
            <p className="pre">{n.preview}</p>
          </section>
        ))
      ) : (
        <p className="muted">No case-file write events have been received.</p>
      )}
      <h3>Open questions</h3>
      {view.report?.open_questions?.length ? (
        <ul>
          {view.report.open_questions.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">No open questions recorded.</p>
      )}
      <h3>Cited findings</h3>
      {view.report?.findings?.map((f) => (
        <button
          className="case-file-citation"
          key={f.id}
          disabled={!f.evidence_ids?.length}
          onClick={() => f.evidence_ids?.[0] && open(f.evidence_ids[0])}
        >
          {f.id} · {f.claim_type.replace(/_/g, " ")}{" "}
          <span aria-hidden="true">↗</span>
        </button>
      ))}
    </section>
  );
}

export function Help({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="How the lab works" onClose={onClose}>
      <div className="help-content">
        <h3>From work to evidence.</h3>
        <p>
          ALIBI is a controlled research environment for investigating AI-worker
          behavior. A worker experiment produces evidence; an independent
          investigator builds a cited account of what those records establish.
        </p>
        <ol>
          <li>Configure an experiment, or open a saved case.</li>
          <li>
            Inspect the records and the investigator’s actual plan and tool
            trace.
          </li>
          <li>Review and lock the report before revealing the answer.</li>
          <li>
            Compare saved runs with evidence hashes and changed conditions
            visible.
          </li>
        </ol>
        <h3>Keep the boundaries clear.</h3>
        <p>
          Live model, recorded AI, scripted fixture and deterministic checks are
          different origins. A credential is not a person. An unavailable record
          cannot establish that an event did not happen.
        </p>
        <p>
          Use ⌘K / Ctrl+K for navigation. Evidence citations open a read-only
          inspector; Escape returns to the source of your selection.
        </p>
      </div>
    </Dialog>
  );
}

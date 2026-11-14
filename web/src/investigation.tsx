import { useContext, useEffect, useRef } from "react";
import type { CaseView, RawView } from "./api";
import type { Run } from "./model";
import { Chips, EvidenceCtx } from "./common";
import { Dialog } from "./dialog";
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
}: {
  onSources: () => void;
  onPlan: () => void;
  onCaseFile: () => void;
  onTrace: () => void;
  onQuestions: () => void;
  hasCase: boolean;
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
      <button onClick={onPlan} disabled={!hasCase}>
        Plan
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

export function PlanView({ run }: { run: Run }) {
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
      <p className="small muted">
        A revised plan and the conflict that caused it will appear only when the
        backend records those events. This view does not infer a revision.
      </p>
    </section>
  );
}

export function TraceView({ run }: { run: Run }) {
  return (
    <section className="trace-view" data-testid="investigation-trace">
      <p className="small muted">
        Actual received events, in causal stream order. Model thoughts are not
        exposed or reconstructed.
      </p>
      {!run.tools.length && <p>No tool calls have been recorded.</p>}
      <ol className="trace-events">
        {run.tools.map((t) => (
          <li key={t.seq}>
            <details>
              <summary>
                <span className="trace-seq mono">{t.seq}</span>
                <span>
                  <b>{t.tool.replace(/_/g, " ")}</b>
                  <small>{t.agent}</small>
                </span>
                <span className={t.ok ? "ok" : "bad"}>
                  {t.ok ? "Completed" : "Failed"}
                  {t.ms != null ? ` · ${t.ms} ms` : ""}
                </span>
              </summary>
              <dl className="facts">
                <dt>Tool</dt>
                <dd className="mono">{t.tool}</dd>
                <dt>Actor</dt>
                <dd>{t.agent}</dd>
                <dt>Input</dt>
                <dd>
                  <pre>
                    {t.args == null
                      ? "No input summary recorded"
                      : typeof t.args === "string"
                        ? t.args
                        : JSON.stringify(t.args, null, 2)}
                  </pre>
                </dd>
                <dt>Result</dt>
                <dd>{t.result_summary || "No result summary recorded"}</dd>
              </dl>
              <Chips ids={t.evidence_ids} />
            </details>
          </li>
        ))}
      </ol>
      <p className="small muted">
        Per-span token and cost values are shown only when supplied by the
        server. Aggregate measured usage is in Details.
      </p>
    </section>
  );
}

export function CaseFile({ view, run }: { view: CaseView; run: Run }) {
  const open = useContext(EvidenceCtx);
  return (
    <section className="case-file" data-testid="case-file">
      <p className="eyebrow">Investigator case file</p>
      <h3>{view.card?.title ?? view.case.title}</h3>
      <p>
        {view.report?.summary || "A report summary has not been recorded yet."}
      </p>
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

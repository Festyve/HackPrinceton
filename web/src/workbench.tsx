import { useContext } from "react";
import { EvidenceCtx } from "./common";
import type { CaseView, Runtime } from "./api";
import type { Run } from "./model";
import { Chips, hhmmss } from "./common";
import { SpendLine, WitnessPanel } from "./phase2";

export const humanState = (state: string) =>
  ({
    created: "Preparing case",
    generating: "Generating evidence",
    frozen: "Evidence frozen",
    investigating: "Investigating",
    awaiting_review: "Awaiting review",
    report_locked: "Report locked",
    scored: "Revealed",
    failed: "Investigation stopped",
    cancelled: "Cancelled",
  })[state] ?? state.replace(/_/g, " ");
export const originLabel = (origin?: string) =>
  ({
    SIM: "Simulated evidence",
    DOCKER: "Captured evidence · Docker containers",
    HYBRID: "Mixed evidence",
  })[origin ?? ""] ??
  origin ??
  "Evidence origin unavailable";

export function Sources({
  view,
  selectedHost,
  onSelect,
  onOpenCase,
}: {
  view: CaseView;
  selectedHost: string | null;
  onSelect: (host: string) => void;
  onOpenCase: (caseId: string) => void;
}) {
  const openEvidence = useContext(EvidenceCtx);
  const sources = view.manifest?.sources ?? [];
  const hosts = [...new Set(sources.map((s) => s.host))];
  const active =
    selectedHost && hosts.includes(selectedHost)
      ? selectedHost
      : hosts.includes("workstation")
        ? "workstation"
        : hosts[0];
  const selected = sources.filter((s) => s.host === active);
  return (
    <aside className="col sources" aria-label="Sources">
      <div className="column-title">
        <h2>Sources</h2>
        <span>{hosts.length} hosts</span>
      </div>
      <p className="small muted">Independent records, one investigation.</p>
      <div
        className="topology"
        data-testid="source-topology"
        aria-label="Hosts in the evidence manifest"
      >
        {hosts.map((host, i) => (
          <button
            key={host}
            className={`source-node ${active === host ? "selected" : ""}`}
            onClick={() => onSelect(host)}
            aria-pressed={active === host}
            data-testid={`source-${host}`}
          >
            <span className="node-icon" aria-hidden>
              {String(i + 1).padStart(2, "0")}
            </span>
            <span>
              <b>{host}</b>
              <small>
                {sources
                  .filter((s) => s.host === host)
                  .some((s) => s.tamper_exposure === "independent_witness")
                  ? "Independent witness"
                  : "Local records"}
              </small>
            </span>
          </button>
        ))}
      </div>
      {!hosts.length && (
        <p className="muted">Sources appear when the evidence is frozen.</p>
      )}
      {active && (
        <section className="source-detail" data-testid="source-detail">
          <p className="eyebrow">Selected source</p>
          <h3>{active}</h3>
          <p className="small">
            {selected.length} artifact{selected.length === 1 ? "" : "s"} ·{" "}
            {selected
              .reduce((sum, s) => sum + s.line_count, 0)
              .toLocaleString()}{" "}
            lines
          </p>
          <h4>Coverage</h4>
          {selected.map((s) => (
            <details key={s.artifact} className="source-artifact">
              <summary>
                {s.artifact.startsWith(s.host + "/")
                  ? s.artifact.slice(s.host.length + 1)
                  : s.artifact}
              </summary>
              <p className="small muted">
                {s.coverage_declared
                  ? "Declared recording window"
                  : "Surviving record bounds"}
              </p>
              <p className="small">
                {s.coverage_start && s.coverage_end
                  ? `${hhmmss(s.coverage_start)}–${hhmmss(s.coverage_end)} UTC`
                  : "Coverage bounds unavailable"}
              </p>
              <p className="small muted">
                {s.coverage_note || "No additional coverage note."}
              </p>
              {!!s.known_gaps?.length && (
                <ul className="coverage-caution">
                  {s.known_gaps.map((g, i) => (
                    <li key={i}>
                      {hhmmss(g.start)}–{hhmmss(g.end)} UTC ·{" "}
                      {g.reason || "Known recording gap"}
                    </li>
                  ))}
                </ul>
              )}
              <span className="small">
                {s.tamper_exposure === "independent_witness"
                  ? "Independent witness"
                  : "Host-local, writable in this model"}
              </span>
              {s.line_count > 0 && (
                <button
                  className="source-open"
                  onClick={() =>
                    openEvidence({ artifact: s.artifact, line: 1 })
                  }
                >
                  Open source record
                </button>
              )}
            </details>
          ))}
        </section>
      )}
      {view.manifest && !view.manifest.capture_complete && (
        <p className="coverage-caution" data-testid="incomplete-evidence">
          Incomplete evidence. {(view.manifest.capture_notes ?? []).join(" ")}
        </p>
      )}
      <WitnessPanel view={view} onOpenCase={onOpenCase} />
      <p className="seal-note">
        {view.case.state === "scored"
          ? "Answer key unsealed"
          : "Answer key sealed"}
        <small>The report locks before the answer is revealed.</small>
      </p>
    </aside>
  );
}

export function RuntimeDetails({
  view,
  run,
  runtime,
}: {
  view: CaseView | null;
  run: Run;
  runtime: Runtime | null;
}) {
  const usage = view?.report?.usage ?? run.usage;
  return (
    <div className="runtime-details">
      <h3>Inference & provenance</h3>
      <dl className="facts">
        <dt>Runtime</dt>
        <dd data-testid="runtime-status">
          {runtime
            ? runtime.live_inference === "CONFIGURED"
              ? "Live AI configured; availability is not a successful model call"
              : "Live AI unavailable"
            : "Server status unavailable"}
        </dd>
        <dt>Reason</dt>
        <dd>{runtime?.live_block_reason ?? "No block reason reported"}</dd>
        <dt>Inference</dt>
        <dd>
          {view?.case.labels.inference_label ?? "Choose a case"}
          {view?.case.labels.worker_choices && (
            <p>{view.case.labels.worker_choices}</p>
          )}
          {view?.case.labels.changed_objective_policy && (
            <p>{view.case.labels.changed_objective_policy}</p>
          )}
        </dd>
        <dt>Playback</dt>
        <dd>{view?.case.labels.playback ?? "No active case"}</dd>
        <dt>Model</dt>
        <dd>{view?.case.labels.model_id ?? "Not reported"}</dd>
        <dt>Investigation</dt>
        <dd data-testid="investigation-mode">
          {view?.case.labels.investigation_mode_label ?? "Not reported"}
        </dd>
        <dt>Evidence</dt>
        <dd>{originLabel(view?.case.labels.evidence_origin)}</dd>
        <dt>Seed</dt>
        <dd>{view?.case.seed ?? "Not reported"}</dd>
        <dt>Bundle hash</dt>
        <dd className="mono">
          {view?.manifest?.raw_bundle_sha256 ?? "Not available"}
        </dd>
        <dt>Report hash</dt>
        <dd className="mono">{view?.report?.report_sha256 ?? "Not locked"}</dd>
      </dl>
      <h3>Measured usage</h3>
      {usage ? (
        <p>
          {usage.llm_calls} model calls ·{" "}
          {(usage.tokens_in ?? 0).toLocaleString()} tokens in /{" "}
          {(usage.tokens_out ?? 0).toLocaleString()} out · {usage.tool_calls}{" "}
          tool calls
          {usage.wall_seconds != null &&
            ` · ${usage.wall_seconds.toFixed(1)} seconds`}
        </p>
      ) : (
        <p className="muted">No usage reported.</p>
      )}
      <SpendLine />
      <h3>Pipeline</h3>
      <ol className="pipe">
        {Object.values(run.stages).map((s) => (
          <li key={s.name}>
            <b>{s.name}</b> · {s.status.replace(/_/g, " ")}
          </li>
        ))}
      </ol>
      {run.todo.length > 0 && (
        <>
          <h3>Investigation plan</h3>
          <ul>
            {run.todo.map((t, i) => (
              <li key={i}>
                {t.text} · {t.status.replace(/_/g, " ")}
              </li>
            ))}
          </ul>
        </>
      )}
      <h3>Tool trace</h3>
      <ul className="tools">
        {run.tools.map((t) => (
          <li key={t.seq}>
            <b className="mono">{t.tool}</b>
            <span className="tag">{t.ok ? "Completed" : "Failed"}</span>
            <p>{t.result_summary}</p>
            <Chips ids={t.evidence_ids} />
          </li>
        ))}
      </ul>
      {!run.tools.length && <p className="muted">No tool events received.</p>}
      {run.notes.length > 0 && (
        <>
          <h3>Case notes</h3>
          {run.notes.map((n, i) => (
            <details key={i}>
              <summary>{n.path}</summary>
              <p className="pre">{n.preview}</p>
            </details>
          ))}
        </>
      )}
    </div>
  );
}

export function ProgressActivity({ run, state }: { run: Run; state: string }) {
  const stopped = state === "failed" || state === "cancelled";
  const tool = run.tools[run.tools.length - 1];
  const active = run.agentOrder.filter(
    (id) => run.agents[id].status !== "finished",
  );
  return (
    <div className="investigation-progress" role="status">
      <p className="eyebrow">{humanState(state)}</p>
      <h2>
        {stopped
          ? "Investigation ended before review"
          : "Following the surviving evidence"}
      </h2>
      <p>
        {tool?.result_summary || "Waiting for the next investigation event."}
      </p>
      <p className="small muted">
        {run.tools.length} tool events received
        {!stopped && active.length ? ` · Working: ${active.join(", ")}` : ""}
      </p>
    </div>
  );
}

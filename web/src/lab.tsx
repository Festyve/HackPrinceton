import { useContext, useEffect, useRef, useState } from "react";
import type { CaseInfo, Runtime } from "./api";
import { labApi, permissionLabel } from "./lab-api";
import type {
  LabOptions,
  LabView,
  OperatorRecord,
  StageView,
} from "./lab-api";
import { SandboxStage, WorkerFace, InvestigatorFace } from "./sandbox-stage";
import { EvidenceCtx, hhmmss, Chips } from "./common";
import { Dialog } from "./dialog";
import { useRecordedPlayback, PlaybackControls } from "./playback";
import { useActionToken, message, words } from "./features/operation";

const POOL = 20;

export function Lab({
  runtime,
  current,
  state,
  onCases,
  onCase,
  onRecording,
  onInvestigate,
}: {
  runtime: Runtime | null;
  current?: CaseInfo | null;
  state?: string;
  onCases: () => void;
  onCase: (id: string) => void | Promise<void>;
  onRecording?: (() => void | Promise<void>) | null;
  onInvestigate?: () => void;
}) {
  const [options, setOptions] = useState<LabOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [investigator, setInvestigator] = useState(10);
  const [permissions, setPermissions] = useState("export_log");
  const [context, setContext] = useState("standard");
  const [variant, setVariant] = useState("incident");
  const [work, setWork] = useState("scripted");
  const [runner, setRunner] = useState("agent-fixture");
  const [mode, setMode] = useState("fast");
  const [seed, setSeed] = useState("11");
  const [stage, setStage] = useState<StageView | null>(null);
  const [armed, setArmed] = useState(false);
  const [playFor, setPlayFor] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);
  const action = useActionToken();
  const supported = runtime?.capabilities?.worker_lab?.endpoint;
  const caseId = current?.lab ? current.case_id : null;
  useEffect(() => {
    if (!supported) return;
    let live = true;
    labApi
      .options()
      .then((o) => {
        if (live) setOptions(o);
      })
      .catch((e) => live && setError(message(e)));
    return () => {
      live = false;
    };
  }, [supported]);
  // The stage is rebuilt from frozen evidence; it never reads the sealed operator record.
  useEffect(() => {
    setStage(null);
    setFinished(false);
    if (!caseId) return;
    let live = true;
    if (armed) {
      setPlayFor(caseId);
      setArmed(false);
    }
    labApi
      .stage(caseId)
      .then((s) => live && setStage(s))
      .catch((e) => live && setError(message(e)));
    return () => {
      live = false;
    };
  }, [caseId]);
  const sabotage = POOL - investigator;
  const solo = mode !== "specialist";
  const agents =
    runner === "deterministic"
      ? []
      : solo
        ? ["Investigator"]
        : ["Lead", "Integrity auditor", "Skeptic"];
  async function run() {
    if (!options || pending) return;
    const body = {
      variant,
      seed: Number(seed),
      rogue_requests: sabotage,
      investigator_requests: investigator,
      rogue_permissions: permissions,
      context_load: context,
      ordinary_work: work,
      runner,
      investigation_mode: mode,
      autostart: true,
    };
    setPending(true);
    setError(null);
    try {
      const result = await labApi.create({
        ...body,
        client_token: action.take(JSON.stringify(body)),
      });
      action.done();
      setArmed(true);
      await onCase(result.case.case_id);
    } catch (e) {
      action.done(e);
      setError(message(e));
    } finally {
      setPending(false);
    }
  }
  async function recording() {
    if (!onRecording || pending) return;
    setPending(true);
    setArmed(true);
    try {
      await onRecording();
    } finally {
      setPending(false);
    }
  }
  const live = work === "model" || runner === "agent-live";
  return (
    <section className="lab-overview demo-lab" data-testid="lab-workspace">
      <div className="demo-config">
        <div className="demo-card power-card">
          <h2>Power balance</h2>
          <div className="power-sides">
            <div className="power-side sabotage">
              <span>Sabotage</span>
              <strong data-testid="count-sabotage">{sabotage}</strong>
              <small>turns</small>
            </div>
            <i aria-hidden="true">vs</i>
            <div className="power-side investigator-allowance">
              <span>Investigator</span>
              <strong data-testid="count-investigator">{investigator}</strong>
              <small>requests</small>
            </div>
          </div>
          <input
            className="power-slider"
            type="range"
            min="1"
            max={POOL - 1}
            step="1"
            value={investigator}
            disabled={!options || pending}
            aria-label="Power balance"
            aria-valuetext={`Sabotage ${sabotage} turns, investigator ${investigator} requests`}
            onChange={(e) => setInvestigator(Number(e.target.value))}
          />
          <div
            className="mode-switch"
            role="radiogroup"
            aria-label="Investigation mode"
          >
            {[
              ["fast", "Solo"],
              ["specialist", "Specialists"],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={mode === id}
                className={mode === id ? "on" : ""}
                disabled={pending || runner === "deterministic"}
                onClick={() => setMode(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="lineup" data-testid="lineup">
            <span className="lineup-group">
              {["W1", "W2", "W3"].map((w) => (
                <span className="chip-bot" key={w}>
                  <WorkerFace />
                  {w}
                </span>
              ))}
            </span>
            <span className="lineup-group">
              {agents.map((a) => (
                <span className="chip-bot chip-sleuth" key={a}>
                  <InvestigatorFace />
                  {a}
                </span>
              ))}
              {!agents.length && (
                <span className="chip-bot">Checks · no agent</span>
              )}
            </span>
          </div>
        </div>
        <div className="demo-run">
          <button
            form="worker-experiment"
            type="submit"
            className={caseId && finished ? "run-btn" : "run-btn primary"}
            data-testid="btn-lab-run"
            disabled={pending || !options}
          >
            {pending
              ? "Preparing sandbox…"
              : caseId
                ? "Run again"
                : "Run sandbox"}{" "}
            <span aria-hidden="true">▶</span>
          </button>
          <span className="mono small muted" data-testid="lab-mode-caption">
            {current?.lab && current.labels?.playback === "REPLAY"
              ? `Showing a recording · ${current.labels.inference_label}`
              : live
                ? "Live model · uses API budget"
                : "Scripted fixture · no model calls"}
          </span>
          {onRecording && (
            <button
              className="linkish"
              data-testid="btn-lab-recording"
              disabled={pending}
              onClick={() => void recording()}
            >
              Open recording
            </button>
          )}
        </div>
        {!supported ? (
          <div role="status" data-testid="worker-runtime-unavailable">
            <h3>Worker experiments unavailable</h3>
            <button onClick={onCases}>Open case investigations →</button>
          </div>
        ) : !options ? (
          !error && <p role="status">Loading worker options…</p>
        ) : (
          <form
            id="worker-experiment"
            onSubmit={(e) => {
              e.preventDefault();
              void run();
            }}
          >
            <details className="advanced-config">
              <summary>Advanced</summary>
              <fieldset disabled={pending} className="config-grid">
                <label>
                  Scenario
                  <select
                    aria-label="Operator scenario"
                    value={variant}
                    onChange={(e) => setVariant(e.target.value)}
                  >
                    {options.variants.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Investigator runner
                  <select
                    aria-label="Investigator"
                    value={runner}
                    onChange={(e) => setRunner(e.target.value)}
                  >
                    <option value="agent-fixture">
                      Scripted agent fixture · no model
                    </option>
                    <option value="deterministic">
                      Deterministic checks · no agent
                    </option>
                    <option
                      value="agent-live"
                      disabled={runtime?.live_inference !== "CONFIGURED"}
                    >
                      Live model
                      {runtime?.live_inference !== "CONFIGURED"
                        ? " · unavailable"
                        : ""}
                    </option>
                  </select>
                </label>
                <label>
                  Workers’ work chosen by
                  <select
                    aria-label="Ordinary worker choices"
                    value={work}
                    onChange={(e) => setWork(e.target.value)}
                  >
                    {options.ordinary_work.map((w) => (
                      <option key={w.id} value={w.id} disabled={!w.available}>
                        {w.label}
                        {!w.available ? " · unavailable" : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Permission profile
                  <select
                    aria-label="Permission profile"
                    value={permissions}
                    onChange={(e) => setPermissions(e.target.value)}
                  >
                    {options.rogue_permissions.map((p) => (
                      <option key={p.id} value={p.id}>
                        {permissionLabel(p.id)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Context load
                  <select
                    aria-label="Evidence/context load"
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                  >
                    {options.context_load.map((c) => (
                      <option key={c.id} value={c.id}>
                        {words(c.id)} · {c.unrelated_records_per_tick} records /
                        tick
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Seed
                  <input
                    aria-label="World seed"
                    type="number"
                    min="0"
                    max="10000000"
                    required
                    value={seed}
                    onChange={(e) => setSeed(e.target.value)}
                  />
                </label>
              </fieldset>
            </details>
          </form>
        )}
        {error && (
          <p role="alert" className="bad">
            Could not{" "}
            {options ? "run the worker experiment" : "load worker options"}:{" "}
            {error}
          </p>
        )}
      </div>
      <div className="demo-watch">
        <SandboxStage
          stage={caseId ? stage : null}
          autoplay={!!caseId && playFor === caseId}
          loading={pending}
          onDone={() => setFinished(true)}
        />
        <div className="demo-next">
          {caseId && finished && stage && (
            <>
              <span className="demo-result">
                {stage.summary.unassigned
                  ? `${stage.summary.workers_with_unassigned_activity.join(", ")}: ${stage.summary.unassigned} unassigned actions · ${stage.summary.local_records_missing} local records missing`
                  : `${stage.summary.routine} routine actions · nothing unassigned`}
              </span>
              <button
                className="primary next-btn"
                data-testid="btn-open-investigation"
                onClick={onInvestigate}
              >
                Open investigation <span aria-hidden="true">→</span>
              </button>
            </>
          )}
        </div>
      </div>
      {caseId && (
        <details className="lab-details">
          <summary>Details</summary>
          <WorkerActivity key={caseId} caseId={caseId} state={state ?? ""} />
        </details>
      )}
    </section>
  );
}

export function WorkerActivity({
  caseId,
  state,
}: {
  caseId: string;
  state: string;
}) {
  const [view, setView] = useState<LabView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [operator, setOperator] = useState<OperatorRecord | null>(null);
  const [operatorPending, setOperatorPending] = useState(false);
  const operatorTrigger = useRef<HTMLButtonElement>(null);
  const open = useContext(EvidenceCtx);
  const playback = useRecordedPlayback(operator?.records.length ?? 0);
  useEffect(() => {
    let live = true;
    setView(null);
    setError(null);
    setOperator(null);
    labApi
      .view(caseId)
      .then((v) => live && setView(v))
      .catch((e) => live && setError(message(e)));
    return () => {
      live = false;
    };
  }, [caseId, state]);
  async function inspectOperator() {
    setOperatorPending(true);
    setError(null);
    try {
      setOperator(await labApi.operator(caseId));
    } catch (e) {
      setError(message(e));
    } finally {
      setOperatorPending(false);
    }
  }
  if (error && !view)
    return <p role="alert">Could not read worker activity: {error}</p>;
  if (!view) return <p role="status">Reading frozen worker activity…</p>;
  return (
    <section className="worker-activity" data-testid="worker-activity">
      <div className="worker-cards">
        {view.config.workers.map((w) => (
          <article key={w.id}>
            <span className="worker-id">{w.id}</span>
            <h3>{words(w.job)}</h3>
            <span className="mono small">{w.account}</span>
            <p>{w.goal}</p>
            <small>
              {view.activity.filter((a) => a.worker === w.id).length} collector
              records in this view
            </small>
          </article>
        ))}
      </div>
      <h3>What the collector recorded</h3>
      <p className="small muted">
        {view.activity_source}. {view.activity.length} of {view.activity_total}{" "}
        records shown. A recorded status is evidence, not the operator’s
        complete action history.
      </p>
      <div className="worker-records">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Worker / account</th>
              <th>Activity</th>
              <th>Recorded status</th>
              <th>Proof</th>
            </tr>
          </thead>
          <tbody>
            {view.activity.map((a, i) => (
              <tr key={`${a.event_id}-${i}`}>
                <td className="mono">{hhmmss(a.t)}</td>
                <td>
                  {a.worker}
                  <small className="mono">{a.account}</small>
                </td>
                <td>
                  {words(a.action)}
                  {a.dataset && <small>{a.dataset}</small>}
                </td>
                <td>{a.status ?? "Not recorded"}</td>
                <td>
                  <button
                    className="linkish"
                    onClick={() => open(a.event_id)}
                    aria-label={`Open worker record ${a.event_id}`}
                  >
                    Open source ↗
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="scheduler-records">
        <summary>Scheduler records ({view.scheduler_records.length})</summary>
        {view.scheduler_records.map((r) => (
          <div key={r.event_id}>
            <time>{hhmmss(r.t)}</time>
            <p>{r.text}</p>
            <Chips ids={[r.event_id]} />
          </div>
        ))}
      </details>
      <div className="operator-boundary">
        <h3>Operator view</h3>
        <p className="small muted">
          Every attempted action and its actual outcome live in a separate
          operator record. The investigator was not given this record.
        </p>
        {view.operator_record.available ? (
          <button
            ref={operatorTrigger}
            data-testid="btn-operator-record"
            disabled={operatorPending}
            onClick={inspectOperator}
          >
            {operatorPending
              ? "Reading operator record…"
              : "Open operator action history"}
          </button>
        ) : (
          <p className="sealed-note" data-testid="operator-sealed">
            Sealed until the report is locked. No hidden worker identity or
            transition is shown here.
          </p>
        )}
        {error && (
          <p role="alert" className="bad">
            {error}
          </p>
        )}
      </div>
      {operator && (
        <Dialog
          returnFocus={operatorTrigger.current}
          title="Operator action history"
          wide
          onClose={() => setOperator(null)}
        >
          <div className="operator-record" data-testid="operator-record">
            <p className="eyebrow">
              Operator view · not investigator knowledge
            </p>
            <p>{operator.label}</p>
            <p>
              {operator.transition
                ? `Recorded objective change: ${operator.transition.worker} at ${hhmmss(operator.transition.t)}, tick ${operator.transition.tick}.`
                : "No objective transition was recorded."}
            </p>
            <p className="small muted">
              This is a recorded action tape. It is never added to questions,
              the case file or an investigator prompt.
            </p>
            <PlaybackControls playback={playback} />
            <ol>
              {operator.records.slice(0, playback.shown).map((r) => (
                <li key={r.seq} data-outcome={r.status}>
                  <div>
                    <span className="mono">
                      {r.seq} · {hhmmss(r.t)}
                    </span>
                    <b>
                      {r.worker} · {words(r.action)}
                    </b>
                    <span
                      className={
                        r.status === "succeeded"
                          ? "ok"
                          : r.status === "failed"
                            ? "bad"
                            : "amber"
                      }
                    >
                      {words(r.status)}
                    </span>
                  </div>
                  <p>{r.outcome}</p>
                  <small className="mono">
                    {r.artifacts.join(" · ") || "No artifact recorded"}
                  </small>
                </li>
              ))}
            </ol>
          </div>
        </Dialog>
      )}
    </section>
  );
}

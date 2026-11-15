import { useContext, useEffect, useRef, useState } from "react";
import type { Runtime } from "./api";
import { labApi, permissionLabel } from "./lab-api";
import type { LabOptions, LabView, OperatorRecord } from "./lab-api";
import { EvidenceCtx, hhmmss, Chips } from "./common";
import { Pip } from "./shell";
import { Dialog } from "./dialog";
import { useRecordedPlayback, PlaybackControls } from "./playback";
import { useActionToken, message, words } from "./features/operation";

export function Lab({
  runtime,
  onCases,
  onCase,
}: {
  runtime: Runtime | null;
  onCases: () => void;
  onCase: (id: string) => void;
}) {
  const [options, setOptions] = useState<LabOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [allocation, setAllocation] = useState("balanced");
  const [permissions, setPermissions] = useState("export_log");
  const [context, setContext] = useState("standard");
  const [variant, setVariant] = useState("incident");
  const [work, setWork] = useState("scripted");
  const [runner, setRunner] = useState("agent-fixture");
  const [mode, setMode] = useState("fast");
  const [seed, setSeed] = useState("11");
  const action = useActionToken();
  const supported = runtime?.capabilities?.worker_lab?.endpoint;
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
  const chosen = options?.presets.find((a) => a.id === allocation);
  async function run() {
    if (!options || pending) return;
    const body = {
      variant,
      seed: Number(seed),
      preset: allocation,
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
      onCase(result.case.case_id);
    } catch (e) {
      action.done(e);
      setError(message(e));
    } finally {
      setPending(false);
    }
  }
  const splits = options?.presets ?? [];
  const presetIndex = Math.max(
    0,
    splits.findIndex((p) => p.id === allocation),
  );
  return (
    <section className="lab-overview design-lab" data-testid="lab-workspace">
      <div className="design-setup-controls">
        <div className="design-card advantage-card">
          <div className="design-label-row">
            <span className="eyebrow">Advantage</span>
            <span className="mono small muted">20-unit pool</span>
          </div>
          <div className="advantage-sides">
            <span className="rogue-avatar" aria-hidden="true">
              ?
            </span>
            <div>
              <span>Sabotage policy</span>
              <strong>
                {chosen?.rogue_requests ?? "—"} <small>turns</small>
              </strong>
            </div>
            <i>vs</i>
            <div className="investigator-allowance">
              <span>Investigator</span>
              <strong>
                {chosen?.investigator_requests ?? "—"} <small>requests</small>
              </strong>
            </div>
            <Pip />
          </div>
          <input
            className="advantage-slider"
            type="range"
            min="0"
            max={Math.max(0, splits.length - 1)}
            step="1"
            value={presetIndex}
            disabled={!options || pending}
            aria-label="Decision allocation preset"
            aria-valuetext={chosen?.label}
            onChange={(e) => setAllocation(splits[Number(e.target.value)].id)}
          />
          <fieldset
            disabled={pending || !options}
            className="allocation-presets"
          >
            <legend className="sr-only">
              Post-transition decision allocation
            </legend>
            {splits.map((a) => (
              <label
                key={a.id}
                className={allocation === a.id ? "selected" : ""}
              >
                <input
                  type="radio"
                  name="allocation"
                  value={a.id}
                  checked={allocation === a.id}
                  onChange={() => setAllocation(a.id)}
                />
                <span>
                  {a.label.split(" · ")[0]}{" "}
                  <small>
                    {a.rogue_requests}/{a.investigator_requests}
                  </small>
                </span>
              </label>
            ))}
          </fieldset>
          <details className="allocation-details">
            <summary>How allocation works</summary>
            <p>
              {options?.preset_note ?? "Loading supported presets…"} Unused
              units do not transfer. Worker faults use a scripted policy;
              investigator requests may use a model.
            </p>
          </details>
        </div>
        <div className="design-run">
          <button
            form="worker-experiment"
            type="submit"
            className="primary"
            data-testid="btn-lab-run"
            disabled={pending || !options}
          >
            {pending ? "Preparing sandbox…" : "Run sandbox"}{" "}
            <span aria-hidden="true">▶</span>
          </button>
          <span className="mono small muted">
            {work === "model" || runner === "agent-live"
              ? "Live model · uses the configured API budget"
              : "Scripted fixture · no model calls"}
          </span>
          <button className="linkish" onClick={onCases}>
            Open a recording instead ↗
          </button>
        </div>
        <div className="design-card rules-card">
          <p className="eyebrow">Rules</p>
          {!supported ? (
            <div role="status" data-testid="worker-runtime-unavailable">
              <h3>Worker experiments unavailable</h3>
              <button onClick={onCases}>Open case investigations →</button>
            </div>
          ) : !options ? (
            <p role="status">Loading worker options…</p>
          ) : (
            <form
              id="worker-experiment"
              onSubmit={(e) => {
                e.preventDefault();
                void run();
              }}
            >
              <fieldset disabled={pending} className="design-rules">
                <label>
                  Rogue can
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
                  Investigator mode
                  <select
                    aria-label="Investigation mode"
                    value={mode}
                    disabled={runner === "deterministic"}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="fast">Fast · one agent</option>
                    <option value="specialist">
                      Specialist · lead, auditor & skeptic
                    </option>
                  </select>
                </label>
              </fieldset>
              <details className="advanced-config" open={undefined}>
                <summary>
                  More <span>Execution · context · seed</span>
                </summary>
                <fieldset disabled={pending} className="config-grid">
                  <label>
                    Operator scenario
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
                    Investigator
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
                    Ordinary worker choices
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
                    Evidence/context load
                    <select
                      aria-label="Evidence/context load"
                      value={context}
                      onChange={(e) => setContext(e.target.value)}
                    >
                      {options.context_load.map((c) => (
                        <option key={c.id} value={c.id}>
                          {words(c.id)} · {c.unrelated_records_per_tick} records
                          / tick
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    World seed
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
                <p className="small muted policy-label">
                  {options.changed_objective_policy}
                </p>
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
      </div>
      <SandboxPreview />
    </section>
  );
}

function SandboxPreview() {
  const files = [
    ["/srv/lab/raw/", "W1", "Ingest datasets", "◇ local"],
    ["/srv/lab/reports/", "W2", "Write summaries", "◇ local"],
    ["Approved archive", "W3", "Archive reports", "◆ archive store"],
    ["/srv/lab/tmp/", "—", "Temporary exports", "◇ local"],
    [
      "Worker activity log",
      "All",
      "Record job actions",
      "◇ local · ◆ collector",
    ],
    ["Scheduler records", "All", "Assign jobs", "◆ independent"],
  ];
  return (
    <div className="sandbox-preview">
      <div className="outside-investigator">
        <div>
          Investigator waits outside
          <small>Read-only access after evidence freezes</small>
        </div>
        <Pip />
      </div>
      <section
        className="sandbox-boundary"
        aria-label="Planned sandbox structure"
      >
        <span className="boundary-caption">Sandbox boundary</span>
        <header>
          <h2>Sandbox</h2>
          <span className="mono small muted">Synthetic lab · 3 workers</span>
          <span className="tag">IDLE</span>
        </header>
        <div className="sandbox-files">
          <div className="sandbox-file table-label">
            <span></span>
            <span>Object / path</span>
            <span>Worker</span>
            <span>Planned work</span>
            <span>Copies</span>
          </div>
          {files.map(([path, worker, job, copies]) => (
            <div className="sandbox-file" key={path}>
              <span className="file-glyph" aria-hidden="true">
                ▯
              </span>
              <code>{path}</code>
              <span className="worker-bubble">{worker}</span>
              <span>{job}</span>
              <small>{copies}</small>
            </div>
          ))}
        </div>
        <div className="sandbox-workers">
          {[
            ["W1", "Ingest", "wk-ingest"],
            ["W2", "Summarize", "wk-report"],
            ["W3", "Archive", "wk-archive"],
          ].map(([id, job, acct]) => (
            <article key={id}>
              <span className="worker-bubble">{id}</span>
              <div>
                {job}
                <small>{acct}</small>
              </div>
            </article>
          ))}
        </div>
        <div className="rogue-notice">
          <span className="rogue-avatar">?</span>
          <div>
            One may change objective
            <small>Scripted fault policy · selected by the scenario</small>
          </div>
        </div>
      </section>
      <div className="independent-witnesses">
        <span className="eyebrow">Beyond the workers’ reach</span>
        <span>◆ Log collector</span>
        <span>◆ Network tap</span>
        <small>◇ host-local copy · ◆ independent witness</small>
      </div>
    </div>
  );
}

export function WorkerActivity({
  caseId,
  state,
  onInvestigate,
}: {
  caseId: string;
  state: string;
  onInvestigate?: () => void;
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
      <div className="section-heading">
        <div>
          <p className="eyebrow">Worker lab · frozen evidence</p>
          <h2>Sandbox recording</h2>
        </div>
        {onInvestigate && (
          <button className="primary" onClick={onInvestigate}>
            Open investigation →
          </button>
        )}
      </div>
      <p className="small provenance-label">
        {view.provenance.ordinary_work_label}
        <br />
        {view.provenance.changed_objective_label}
      </p>
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
      <div className="worker-conditions">
        <span>{view.conditions.preset_label}</span>
        <span>
          {view.conditions.rogue_requests} scripted turns /{" "}
          {view.conditions.investigator_requests} investigator requests
        </span>
        <span>{permissionLabel(view.conditions.rogue_permissions)}</span>
        <span>{words(view.conditions.context_load)} context</span>
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

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
  return (
    <section className="lab-overview" data-testid="lab-workspace">
      <div className="lab-intro">
        <div>
          <p className="eyebrow">Controlled worker experiments</p>
          <h2>
            Ordinary work.
            <br />
            <em>Extraordinary evidence.</em>
          </h2>
          <p>
            Understand what a worker did, what survived in the records, and what
            an independent investigator can establish.
          </p>
        </div>
        <div className="lab-method">
          <span>
            01 <b>Configure</b>
          </span>
          <span>
            02 <b>Run & observe</b>
          </span>
          <span>
            03 <b>Investigate</b>
          </span>
          <span>
            04 <b>Compare</b>
          </span>
        </div>
      </div>
      <div className="lab-configuration">
        <div className="section-heading">
          <div>
            <p className="eyebrow">
              Operator setup · separate from investigator knowledge
            </p>
            <h3>Decision allocation</h3>
          </div>
          <div className="lab-config-actions">
            <span className="tag">
              {options ? options.version : "Checking availability"}
            </span>
            {options && (
              <button
                form="worker-experiment"
                type="submit"
                className="primary"
                data-testid="btn-lab-run"
                disabled={pending}
              >
                {pending
                  ? "Running workers & freezing evidence…"
                  : work === "model" || runner === "agent-live"
                    ? "Run experiment · uses configured model"
                    : "Run scripted worker experiment"}
              </button>
            )}
          </div>
        </div>
        {!supported ? (
          <div
            className="worker-availability"
            role="status"
            data-testid="worker-runtime-unavailable"
          >
            <Pip />
            <div>
              <h3>Worker experiments are unavailable on this server</h3>
              <p>
                No worker action or model call has been started. Saved
                investigations remain available.
              </p>
              <button onClick={onCases}>
                Explore working case investigations →
              </button>
            </div>
          </div>
        ) : !options ? (
          <p role="status">Loading worker experiment options…</p>
        ) : (
          <form
            id="worker-experiment"
            onSubmit={(e) => {
              e.preventDefault();
              void run();
            }}
          >
            <fieldset disabled={pending} className="allocation-presets">
              <legend className="sr-only">
                Post-transition decision allocation
              </legend>
              {options.presets.map((a) => (
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
                    <strong>{a.label.split(" · ")[1]}</strong>
                    <b>{a.label.split(" · ")[0]}</b>
                    <small>
                      {a.rogue_requests} changed-worker turns /{" "}
                      {a.investigator_requests} investigator requests
                    </small>
                  </span>
                </label>
              ))}
            </fieldset>
            <p className="allocation-explanation">
              This 20-unit pool allows{" "}
              <b>
                {chosen?.rogue_requests} scripted turns for the changed worker
              </b>{" "}
              and{" "}
              <b>{chosen?.investigator_requests} investigator model requests</b>
              , including retries and specialists. Ordinary work has a separate
              allowance. Unused units do not transfer between sides.
            </p>
            <details className="advanced-config">
              <summary>Permissions, context & execution</summary>
              <fieldset className="config-grid" disabled={pending}>
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
                  <small>
                    {options.rogue_permissions
                      .find((p) => p.id === permissions)
                      ?.actions.map(words)
                      .join(" · ")}
                  </small>
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
                        {words(c.id)} · {c.unrelated_records_per_tick} unrelated
                        records / tick
                      </option>
                    ))}
                  </select>
                </label>
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
                {runner !== "deterministic" && (
                  <label>
                    Investigation mode
                    <select
                      aria-label="Investigation mode"
                      value={mode}
                      onChange={(e) => setMode(e.target.value)}
                    >
                      <option value="fast">Fast · one agent</option>
                      <option value="specialist">
                        Specialist · lead, auditor & skeptic
                      </option>
                    </select>
                  </label>
                )}
              </fieldset>
              <p className="small muted">
                A permission change creates a new execution. An
                investigator-budget comparison reuses the frozen evidence. No
                worker can alter the trusted collector or reach outside this
                simulated world.
              </p>
            </details>
            <p className="small muted policy-label">
              {options.changed_objective_policy}
            </p>
            <div className="lab-run-action">
              <span className="small muted">
                {work === "scripted" && runner !== "agent-live"
                  ? "Scripted workers and offline investigation. No model calls."
                  : "A deliberate run can make billed model requests through this server’s spending limit."}
              </span>
            </div>
          </form>
        )}
        {error && (
          <p role="alert" className="bad">
            {options
              ? "Could not run the worker experiment"
              : "Could not load worker options"}
            : {error}
          </p>
        )}
      </div>
      <div className="boundary-note">
        <span aria-hidden="true">⌕</span>
        <p>
          <b>Outside the sandbox.</b> The investigator receives read-only
          evidence. Operator objectives, transitions and the answer key are kept
          separate.
        </p>
      </div>
    </section>
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
          <p className="eyebrow">Frozen evidence / worker activity</p>
          <h2>Three workers. A trail to follow.</h2>
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

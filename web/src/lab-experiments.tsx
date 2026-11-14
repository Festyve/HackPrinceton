import { useEffect, useState } from "react";
import type { CaseInfo, Runtime } from "./api";
import { labApi, permissionLabel } from "./lab-api";
import type { LabRuns } from "./lab-api";
import { humanState } from "./workbench";
import { ratio } from "./common";
import { message, useActionToken, words } from "./features/operation";

export function LabExperiments({
  cases,
  currentId,
  runtime,
  onOpen,
}: {
  cases: CaseInfo[];
  currentId?: string;
  runtime: Runtime | null;
  onOpen: (id: string) => void;
}) {
  const labs = cases.filter((c) => c.lab);
  const [id, setId] = useState(
    currentId && labs.some((c) => c.case_id === currentId)
      ? currentId
      : (labs[0]?.case_id ?? ""),
  );
  const [runs, setRuns] = useState<LabRuns | null>(null);
  const [kind, setKind] = useState("investigator_budget");
  const [requests, setRequests] = useState(4);
  const [permissions, setPermissions] = useState("export_only");
  const [runner, setRunner] = useState("agent-fixture");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const action = useActionToken();
  const parent = labs.find((c) => c.case_id === id);
  useEffect(() => {
    if (!id && labs.length) setId(labs[0].case_id);
  }, [id, cases]);
  useEffect(() => {
    setRequests(parent?.lab?.conditions.investigator_requests === 4 ? 16 : 4);
    setPermissions(
      parent?.lab?.conditions.rogue_permissions === "export_only"
        ? "export_log"
        : "export_only",
    );
    setRunner(parent?.runner_id ?? "agent-fixture");
  }, [id]);
  useEffect(() => {
    if (!id) return;
    let live = true;
    setRuns(null);
    setError(null);
    labApi
      .comparisons(id)
      .then((r) => live && setRuns(r))
      .catch((e) => live && setError(message(e)));
    return () => {
      live = false;
    };
  }, [id, refresh]);
  if (!labs.length) return null;
  const unchanged =
    kind === "investigator_budget"
      ? requests === parent?.lab?.conditions.investigator_requests
      : permissions === parent?.lab?.conditions.rogue_permissions;
  async function compare() {
    if (!id || pending || unchanged) return;
    const body = {
      kind,
      ...(kind === "investigator_budget"
        ? { investigator_requests: requests }
        : { rogue_permissions: permissions }),
      runner,
      autostart: true,
    };
    setPending(true);
    setError(null);
    try {
      const made = await labApi.compare(id, {
        ...body,
        client_token: action.take(`${id}:${JSON.stringify(body)}`),
      });
      action.done();
      onOpen(made.case.case_id);
    } catch (e) {
      action.done(e);
      setError(message(e));
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="lab-experiments" data-testid="lab-experiments">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Controlled comparisons</p>
          <h2>Change one condition.</h2>
        </div>
        <button
          onClick={() => setRefresh((v) => v + 1)}
          disabled={!id || pending}
        >
          Refresh saved results
        </button>
      </div>
      <label className="lab-parent">
        Starting worker run
        <select
          aria-label="Starting worker run"
          value={id}
          disabled={pending}
          onChange={(e) => setId(e.target.value)}
        >
          {labs.map((c) => (
            <option key={c.case_id} value={c.case_id}>
              {c.title} · {c.case_id.slice(-6)} · {humanState(c.state)}
            </option>
          ))}
        </select>
      </label>
      <details className="comparison-options">
        <summary>Create a controlled comparison</summary>
        <form
          className="comparison-create"
          onSubmit={(e) => {
            e.preventDefault();
            void compare();
          }}
        >
          <fieldset disabled={pending}>
            <legend>Create a separate comparison run</legend>
            <label>
              Variable to change
              <select
                aria-label="Variable to change"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                <option value="investigator_budget">
                  Investigator request allowance · same evidence
                </option>
                <option value="rogue_permissions">
                  Worker permissions · new execution
                </option>
              </select>
            </label>
            {kind === "investigator_budget" ? (
              <label>
                Investigator request allowance
                <input
                  aria-label="Investigator request allowance"
                  type="number"
                  min="1"
                  max="40"
                  required
                  value={requests}
                  onChange={(e) => setRequests(Number(e.target.value))}
                />
              </label>
            ) : (
              <label>
                New permission profile
                <select
                  aria-label="New permission profile"
                  value={permissions}
                  onChange={(e) => setPermissions(e.target.value)}
                >
                  {["export_only", "export_log", "export_log_artifact"].map(
                    (p) => (
                      <option key={p} value={p}>
                        {permissionLabel(p)}
                      </option>
                    ),
                  )}
                </select>
              </label>
            )}
            <label>
              Investigator for comparison
              <select
                aria-label="Investigator for comparison"
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
          </fieldset>
          <p className="comparison-variable">
            {kind === "investigator_budget"
              ? `Reuse the exact frozen evidence; change the investigator allowance from ${parent?.lab?.conditions.investigator_requests ?? "…"} to ${requests} model requests.`
              : `Run a new execution with ${permissionLabel(permissions).toLowerCase()}; replay the original ordinary choices. Evidence may differ.`}
            {parent?.runner_id !== runner &&
              " The investigator system also changes; this does not isolate the selected variable."}
          </p>
          <button
            className="primary"
            data-testid="btn-lab-compare"
            disabled={pending || unchanged}
          >
            {pending
              ? "Creating comparison…"
              : runner === "agent-live"
                ? "Create comparison · uses configured model"
                : "Create offline comparison"}
          </button>
          {unchanged && (
            <p className="small muted">
              Choose a value that differs from the starting run.
            </p>
          )}
        </form>
      </details>
      {error && (
        <p role="alert" className="bad">
          Could not load or create this comparison: {error}
        </p>
      )}
      {!runs && !error && (
        <p role="status">Reading this family of saved runs…</p>
      )}
      {runs && (
        <>
          <p className="small muted">{runs.note}</p>
          <div className="tablewrap">
            <table data-testid="lab-comparison-table">
              <thead>
                <tr>
                  <th>Saved run / changed condition</th>
                  <th>Evidence</th>
                  <th>State / outcome</th>
                  <th>Investigator requests used / allowed</th>
                  <th>Findings</th>
                  <th>Measured use</th>
                  <th>Revealed score</th>
                </tr>
              </thead>
              <tbody>
                {runs.runs.map((r) => (
                  <tr key={r.case_id}>
                    <td>
                      <button
                        className="linkish"
                        onClick={() => onOpen(r.case_id)}
                      >
                        {r.case_id} ↗
                      </button>
                      <small>
                        {r.lineage.changed
                          ? Object.entries(r.lineage.changed)
                              .map(
                                ([k, v]) =>
                                  `${words(k)}: ${String(v.from)} → ${String(v.to)}`,
                              )
                              .join("; ")
                          : "Original execution"}
                      </small>
                      <small>{r.labels.inference_label}</small>
                      <small>{r.labels.worker_choices}</small>
                      <small>{r.labels.changed_objective_policy}</small>
                    </td>
                    <td>
                      <span className="mono">{r.bundle_id}</span>
                      <small>
                        {r.lineage.comparison === "rogue_permissions"
                          ? "New execution"
                          : r.lineage.same_evidence_as_parent
                            ? "Same frozen evidence as parent"
                            : "Original frozen evidence"}
                      </small>
                    </td>
                    <td>
                      {humanState(r.state)}
                      <small>{r.outcome}</small>
                      {(r.stop_reason || r.error) && (
                        <small className="amber">
                          {r.stop_reason || r.error}
                        </small>
                      )}
                    </td>
                    <td>
                      {r.used?.llm_calls ?? "Not recorded"} /{" "}
                      {r.allowed.investigator_requests}
                      <small>
                        {r.allowed.rogue_requests} scripted turns allowed
                      </small>
                    </td>
                    <td>
                      {r.findings
                        ? `${r.findings.total} total · ${r.findings.incident_allegations_accepted} verified allegations`
                        : "No report"}
                    </td>
                    <td>
                      {r.used ? (
                        <>
                          {r.used.tokens_in ?? "?"} in /{" "}
                          {r.used.tokens_out ?? "?"} out
                          <small>
                            {r.used.cost_estimate_usd == null
                              ? "Cost not recorded"
                              : `$${r.used.cost_estimate_usd.toFixed(4)} estimated`}
                          </small>
                        </>
                      ) : (
                        "Not recorded"
                      )}
                    </td>
                    <td>
                      {r.scored ? (
                        <>
                          {ratio(r.scored.effects_established)}
                          <small>
                            Benign false allegation:{" "}
                            {r.scored.benign_false_alert == null
                              ? "N/A"
                              : String(r.scored.benign_false_alert)}
                          </small>
                        </>
                      ) : (
                        "Not revealed"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

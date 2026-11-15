import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { CaseInfo, Ratio, Runtime } from "./api";
import { api } from "./api";
import { labApi, permissionLabel } from "./lab-api";
import { filesApi } from "./files-api";
import type { ExperimentRun, ExperimentRuns } from "./files-api";
import { humanState } from "./workbench";
import { ratio } from "./common";
import { message, useActionToken, words } from "./features/operation";

type Kind = "investigator_budget" | "workflow" | "rogue_permissions";
const PERMISSIONS = ["export_only", "export_log", "export_log_artifact"];
const lineup = (m: unknown) =>
  m === "fast" ? "Solo" : m === "specialist" ? "Specialists" : "No agent";
const runnerName = (r: unknown) =>
  ({
    "agent-fixture": "Scripted agent",
    deterministic: "Deterministic checks",
    "agent-live": "Live model",
  })[String(r)] ?? "Another investigator";

/** Every recorded difference from the first run, in plain words. */
function changes(r: ExperimentRun): Array<{ run: string; text: string }> {
  return Object.entries(r.lineage.changed ?? {}).map(([key, v]) => {
    if (key === "investigator_requests")
      return {
        run: `Requests ${v.from} → ${v.to}`,
        text: `Investigator requests: ${v.from} → ${v.to}`,
      };
    if (key === "investigation_mode")
      return {
        run: `${lineup(v.from)} → ${lineup(v.to)}`,
        text: `Investigator lineup: ${lineup(v.from)} → ${lineup(v.to)}`,
      };
    if (key === "rogue_permissions")
      return {
        run: "Other permissions",
        text: `Worker permissions: ${permissionLabel(String(v.from))} → ${permissionLabel(String(v.to))}`,
      };
    if (key === "runner")
      return {
        run: "Other investigator",
        text: `Investigator: ${runnerName(v.from)} → ${runnerName(v.to)}`,
      };
    return { run: words(key), text: `${words(key)} changed` };
  });
}
const isRoot = (r: ExperimentRun) => r.lineage.parent_case_id == null;

const LinkIcon = () => (
  <svg
    viewBox="0 0 16 16"
    width="14"
    height="14"
    aria-hidden="true"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
  >
    <path d="M6.5 9.5l3-3M7 4.5l1-1a2.5 2.5 0 013.5 3.5l-1 1M9 11.500l-1 1A2.5 2.5 0 014.500 9l1-1" />
  </svg>
);

function Caught({ r, withheld }: { r: ExperimentRun; withheld: boolean }) {
  if (!r.scored)
    return withheld ? (
      <span className="xp-muted">Hidden until every report is locked</span>
    ) : (
      <span className="xp-muted" title="Not revealed">
        —
      </span>
    );
  const { num, den } = r.scored.effects_established;
  if (!den)
    return (
      <span>
        Clean control ·{" "}
        {r.scored.benign_false_alert == null
          ? "nothing to catch"
          : r.scored.benign_false_alert
            ? "false alarm raised"
            : "no false alarm"}
      </span>
    );
  return (
    <span className="xp-score">
      <span
        className="xp-bar"
        role="img"
        aria-label={`${num} of ${den} caught`}
      >
        <i style={{ width: `${(100 * num) / den}%` }} />
      </span>
      <b>
        {num} / {den}
      </b>
    </span>
  );
}

type Point = {
  id: string;
  x: number;
  turns: number;
  solo: boolean;
  num: number | null;
  den: number | null;
};

/** Caught vs investigator budget: one dot per lab run on this server. */
function ExperimentsChart({
  cases,
  onOpen,
}: {
  cases: CaseInfo[];
  onOpen: (id: string) => void;
}) {
  const labs = cases.filter(
    (c) =>
      c.lab &&
      (c.investigation_mode === "fast" || c.investigation_mode === "specialist"),
  );
  const key = labs.map((c) => `${c.case_id}:${c.state}`).join("|");
  const [recall, setRecall] = useState<Record<string, Ratio | null>>({});
  useEffect(() => {
    let live = true;
    Promise.all(
      labs.map((c) =>
        api
          .getCase(c.case_id)
          .then(
            (v) =>
              [
                c.case_id,
                ((v.reveal?.score as { step_recall?: Ratio | null } | undefined)
                  ?.step_recall ?? null) as Ratio | null,
              ] as const,
          )
          .catch(() => [c.case_id, null] as const),
      ),
    ).then((pairs) => live && setRecall(Object.fromEntries(pairs)));
    return () => {
      live = false;
    };
  }, [key]);
  const points: Point[] = labs.map((c) => {
    const r = recall[c.case_id];
    const ok = r && r.den != null && r.den > 0 && r.num != null;
    return {
      id: c.case_id,
      x: c.lab!.conditions.investigator_requests,
      turns: c.lab!.conditions.rogue_requests,
      solo: c.investigation_mode === "fast",
      num: ok ? r!.num! : null,
      den: ok ? r!.den! : null,
    };
  });
  const revealed = points.filter((p) => p.den != null);
  const W = 920,
    H = 210,
    L = 44,
    R = 16,
    T = 14,
    B = 38;
  const sx = (x: number) => L + ((x - 1) / 18) * (W - L - R);
  const sy = (f: number) => T + (1 - f) * (H - T - B);
  // spread dots that share a spot
  const seen: Record<string, number> = {};
  const nudge = (p: Point) => {
    const k = `${p.x}:${p.den == null ? "u" : (p.num! / p.den!).toFixed(3)}`;
    const n = (seen[k] = (seen[k] ?? -1) + 1);
    return n === 0 ? 0 : (n % 2 ? 1 : -1) * Math.ceil(n / 2) * 9;
  };
  return (
    <figure className="xc" data-testid="experiments-chart">
      <figcaption className="xc-head">
        <h3>Caught vs investigator budget</h3>
        {revealed.length >= 2 && (
          <span className="xc-legend">
            <span>
              <i className="xc-dot solo" /> Solo
            </span>
            <span>
              <i className="xc-dot spec" /> Specialists
            </span>
            <span>
              <i className="xc-dot hollow" /> Not revealed
            </span>
          </span>
        )}
      </figcaption>
      {revealed.length < 2 ? (
        <p className="xc-empty">
          Run the lab at a few settings and reveal the results to compare.
        </p>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="Effects caught by investigator requests"
          className="xc-svg"
        >
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line
                className="xc-grid"
                x1={L}
                x2={W - R}
                y1={sy(f)}
                y2={sy(f)}
              />
              <text className="xc-tick" x={L - 8} y={sy(f) + 4} textAnchor="end">
                {Math.round(f * 100)}%
              </text>
            </g>
          ))}
          {[1, 5, 10, 15, 19].map((x) => (
            <text
              key={x}
              className="xc-tick"
              x={sx(x)}
              y={H - B + 16}
              textAnchor="middle"
            >
              {x}
            </text>
          ))}
          <text
            className="xc-axis"
            x={(L + W - R) / 2}
            y={H - 4}
            textAnchor="middle"
          >
            Investigator requests
          </text>
          {points.map((p) => {
            const hollow = p.den == null;
            const cx = sx(Math.min(19, Math.max(1, p.x))) + nudge(p);
            const cy = hollow ? sy(0) : sy(p.num! / p.den!);
            return (
              <circle
                key={p.id}
                data-run={p.id}
                className={`xc-pt ${p.solo ? "solo" : "spec"} ${hollow ? "hollow" : ""}`}
                cx={cx}
                cy={cy}
                r={hollow ? 5 : 6.5}
                onClick={() => onOpen(p.id)}
              >
                <title>
                  {`${p.solo ? "Solo" : "Specialists"} · ${p.x} investigator requests · ${p.turns} saboteur turns · ${
                    hollow ? "not revealed" : `${p.num} / ${p.den} caught`
                  }`}
                </title>
              </circle>
            );
          })}
        </svg>
      )}
    </figure>
  );
}

export function LabExperiments({
  cases,
  currentId,
  runtime,
  onOpen,
  children,
}: {
  cases: CaseInfo[];
  currentId?: string;
  runtime: Runtime | null;
  onOpen: (id: string) => void;
  /** Older expert panels, shown under Details. */
  children?: ReactNode;
}) {
  const labs = cases.filter((c) => c.lab);
  const roots = labs.filter((c) => c.lab!.lineage.parent_case_id == null);
  const current = labs.find((c) => c.case_id === currentId);
  const [id, setId] = useState(
    current?.lab?.lineage.root_case_id ?? roots[0]?.case_id ?? "",
  );
  const [runs, setRuns] = useState<ExperimentRuns | null>(null);
  const [kind, setKind] = useState<Kind>("investigator_budget");
  const [requests, setRequests] = useState(4);
  const [permissions, setPermissions] = useState("export_only");
  const [runner, setRunner] = useState("agent-fixture");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const action = useActionToken();
  const parent = labs.find((c) => c.case_id === id);
  const base = parent?.lab?.conditions;
  const otherLineup =
    parent?.investigation_mode === "fast"
      ? "specialist"
      : parent?.investigation_mode === "specialist"
        ? "fast"
        : null;
  useEffect(() => {
    if (!id && roots.length) setId(roots[0].case_id);
  }, [id, cases]);
  useEffect(() => {
    setRequests(base?.investigator_requests === 4 ? 16 : 4);
    setPermissions(
      base?.rogue_permissions === "export_only" ? "export_log" : "export_only",
    );
    setRunner(parent?.runner_id ?? "agent-fixture");
  }, [id, parent?.runner_id]);
  useEffect(() => {
    if (!id) return;
    let live = true;
    setRuns(null);
    setError(null);
    filesApi
      .experiment(id)
      .then((r) => live && setRuns(r))
      .catch((e) => live && setError(message(e)));
    return () => {
      live = false;
    };
  }, [id, refresh]);
  const unchanged =
    kind === "investigator_budget"
      ? requests === base?.investigator_requests
      : kind === "workflow"
        ? !otherLineup
        : permissions === base?.rogue_permissions;
  async function compare() {
    if (!id || pending || unchanged) return;
    const body = {
      kind,
      ...(kind === "investigator_budget"
        ? { investigator_requests: requests }
        : kind === "workflow"
          ? { investigation_mode: otherLineup }
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
  const rows = runs
    ? [...runs.runs].sort((a, b) => Number(isRoot(b)) - Number(isRoot(a)))
    : [];
  const first = rows.find(isRoot);
  const withheld = !!runs?.scores_withheld;
  const sameEvidence = kind !== "rogue_permissions";
  return (
    <section className="lab-experiments xp" data-testid="lab-experiments">
      <ExperimentsChart cases={cases} onOpen={onOpen} />
      {!roots.length ? (
        <p className="xp-empty">No experiments yet. Run one in Lab.</p>
      ) : (
        <>
          <form
            className="xp-controls"
            onSubmit={(e) => {
              e.preventDefault();
              void compare();
            }}
          >
            <label className="xp-family">
              <span>Experiment</span>
              <select
                aria-label="Starting worker run"
                value={id}
                disabled={pending}
                onChange={(e) => setId(e.target.value)}
              >
                {roots.map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    {c.title ?? c.case_id} · {humanState(c.state)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Compare with</span>
              <select
                aria-label="Variable to change"
                value={kind}
                disabled={pending}
                onChange={(e) => setKind(e.target.value as Kind)}
              >
                <option value="investigator_budget">
                  Investigator requests
                </option>
                <option value="workflow">Lineup</option>
                <option value="rogue_permissions">Permissions</option>
              </select>
            </label>
            {kind === "investigator_budget" ? (
              <input
                aria-label="Investigator request allowance"
                type="number"
                min="1"
                max="40"
                required
                disabled={pending}
                value={requests}
                onChange={(e) => setRequests(Number(e.target.value))}
              />
            ) : kind === "workflow" ? (
              <select
                aria-label="Investigator lineup"
                disabled={pending || !otherLineup}
                value={otherLineup ?? ""}
                onChange={() => undefined}
              >
                <option value={otherLineup ?? ""}>
                  {otherLineup
                    ? lineup(otherLineup)
                    : "First run has no agent"}
                </option>
              </select>
            ) : (
              <select
                aria-label="New permission profile"
                disabled={pending}
                value={permissions}
                onChange={(e) => setPermissions(e.target.value)}
              >
                {PERMISSIONS.map((p) => (
                  <option
                    key={p}
                    value={p}
                    disabled={p === base?.rogue_permissions}
                  >
                    {permissionLabel(p)}
                  </option>
                ))}
              </select>
            )}
            <button
              className="primary"
              data-testid="btn-lab-compare"
              disabled={pending || unchanged}
            >
              {pending ? "Creating…" : "Create"}
            </button>
            <span
              className={`comparison-variable xp-hint ${sameEvidence ? "same" : ""}`}
            >
              {sameEvidence ? (
                <>
                  <LinkIcon /> Same evidence
                </>
              ) : (
                "New execution"
              )}
            </span>
          </form>
          {error && (
            <p role="alert" className="xp-error">
              {error}
            </p>
          )}
          {!runs && !error && <p role="status">Loading runs…</p>}
          {runs && (
            <>
              <div className="xp-tablewrap">
                <table className="xp-table" data-testid="lab-comparison-table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Changed</th>
                      <th>Evidence</th>
                      <th>Caught</th>
                      <th>Requests used</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const ch = changes(r);
                      const same =
                        !isRoot(r) &&
                        r.lineage.comparison !== "rogue_permissions" &&
                        (r.lineage.same_evidence_as_parent === true ||
                          (!!first && r.bundle_id === first.bundle_id));
                      return (
                        <tr
                          key={r.case_id}
                          data-run={r.case_id}
                          className={r.case_id === currentId ? "current" : ""}
                          onClick={() => onOpen(r.case_id)}
                        >
                          <td>
                            <button
                              className="xp-run"
                              onClick={(e) => {
                                e.stopPropagation();
                                onOpen(r.case_id);
                              }}
                            >
                              {isRoot(r)
                                ? "First run"
                                : ch.map((c) => c.run).join(" + ") ||
                                  "Repeat run"}
                            </button>
                            <small>{humanState(r.state)}</small>
                          </td>
                          <td>
                            {isRoot(r) ? (
                              <span className="xp-muted">Baseline</span>
                            ) : ch.length ? (
                              ch.map((c) => <div key={c.text}>{c.text}</div>)
                            ) : (
                              <span className="xp-muted">Nothing recorded</span>
                            )}
                          </td>
                          <td>
                            {isRoot(r) ? (
                              <span className="xp-muted">Original</span>
                            ) : same ? (
                              <span className="xp-same">
                                <LinkIcon /> Same
                              </span>
                            ) : (
                              "New execution"
                            )}
                          </td>
                          <td>
                            <Caught r={r} withheld={withheld} />
                          </td>
                          <td>
                            {r.used?.llm_calls == null ? (
                              <span className="xp-muted">Not recorded</span>
                            ) : (
                              `${r.used.llm_calls} of ${r.allowed.investigator_requests + ((r.allowed as { extra_requests_granted_on_resume?: number }).extra_requests_granted_on_resume ?? 0)}`
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="xp-rule">
                A budget comparison is controlled only when the evidence is the
                same.
              </p>
            </>
          )}
        </>
      )}
      <details className="xp-details" data-testid="experiment-details">
        <summary>Details</summary>
        {roots.length > 0 && (
          <div className="xp-details-row">
            <label>
              Investigator for comparison
              <select
                aria-label="Investigator for comparison"
                value={runner}
                disabled={pending}
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
            <button
              type="button"
              onClick={() => setRefresh((v) => v + 1)}
              disabled={!id || pending}
            >
              Refresh saved results
            </button>
          </div>
        )}
        {runs && (
          <>
            <p className="small muted">{runs.note}</p>
            <div className="tablewrap">
              <table data-testid="lab-comparison-details">
                <thead>
                  <tr>
                    <th>Saved run / recorded labels</th>
                    <th>Evidence bundle</th>
                    <th>State / outcome</th>
                    <th>Requests used / allowed</th>
                    <th>Findings</th>
                    <th>Measured use</th>
                    <th>Revealed score</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.case_id}>
                      <td>
                        <button
                          className="linkish"
                          onClick={() => onOpen(r.case_id)}
                        >
                          {r.case_id} ↗
                        </button>
                        <small>{r.labels.inference_label}</small>
                        <small>{r.labels.worker_choices}</small>
                        <small>{r.labels.changed_objective_policy}</small>
                      </td>
                      <td>
                        <span className="mono">{r.bundle_id}</span>
                        <small>
                          {permissionLabel(r.conditions.rogue_permissions)} ·{" "}
                          {r.conditions.context_load} context
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
                        ) : withheld ? (
                          "Withheld"
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
        {children}
      </details>
    </section>
  );
}

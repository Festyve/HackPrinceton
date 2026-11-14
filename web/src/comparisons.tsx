import { useEffect, useState } from "react";
import { api } from "./api";
import type { CaseInfo, CaseView } from "./api";
import { humanState, originLabel } from "./workbench";
import { ratio } from "./common";

export function SavedComparison({
  cases,
  onOpen,
}: {
  cases: CaseInfo[];
  onOpen: (id: string) => void;
}) {
  const [ids, setIds] = useState<[string, string]>(() => {
    try {
      const saved: unknown = JSON.parse(
        localStorage.getItem("alibi:comparison:v1") ?? "null",
      );
      if (
        Array.isArray(saved) &&
        saved.length === 2 &&
        saved.every((id) => typeof id === "string")
      )
        return saved as [string, string];
    } catch {
      /* Comparison remains usable when browser storage is unavailable. */
    }
    return ["", ""];
  });
  useEffect(() => {
    try {
      localStorage.setItem("alibi:comparison:v1", JSON.stringify(ids));
    } catch {
      /* optional convenience */
    }
  }, [ids]);
  const [views, setViews] = useState<[CaseView | null, CaseView | null]>([
    null,
    null,
  ]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let live = true;
    setError(null);
    setLoading(false);
    setViews([null, null]);
    if (!ids[0] || !ids[1]) return;
    setLoading(true);
    Promise.all(ids.map((id) => api.getCase(id)))
      .then((v) => {
        if (live) setViews(v as [CaseView, CaseView]);
      })
      .catch(
        (e) => live && setError(e instanceof Error ? e.message : String(e)),
      )
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [ids]);
  const sameHash =
    !!views[0]?.manifest?.raw_bundle_sha256 &&
    views[0]?.manifest?.raw_bundle_sha256 ===
      views[1]?.manifest?.raw_bundle_sha256;
  const both = views[0] && views[1];
  const changes: string[] = [];
  const [left, right] = views;
  if (both) {
    if (left!.case.runner_id !== right!.case.runner_id)
      changes.push("investigator system");
    if (left!.case.investigation_mode !== right!.case.investigation_mode)
      changes.push("investigation mode");
    if (left!.case.lab && right!.case.lab) {
      const a = left!.case.lab.conditions,
        b = right!.case.lab.conditions;
      if (a.investigator_requests !== b.investigator_requests)
        changes.push(
          `investigator allowance (${a.investigator_requests} → ${b.investigator_requests} requests)`,
        );
      if (a.rogue_permissions !== b.rogue_permissions)
        changes.push("worker permissions / execution");
      if (a.context_load !== b.context_load) changes.push("context load");
    }
  }
  const identity = !sameHash
    ? "Different execution or evidence. This comparison does not isolate a budget effect."
    : changes.length
      ? `Same frozen evidence bytes; changed ${changes.join(", ")}.${changes.some((c) => c.includes("execution")) ? " These are different execution conditions." : ""}`
      : "Same frozen evidence; no changed resource condition is recorded here.";
  return (
    <section className="saved-comparison" data-testid="saved-comparison">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Inspect a comparison</p>
          <h2>Two runs. What changed?</h2>
        </div>
        <span className="tag">Saved results · read-only</span>
      </div>
      <p className="muted">
        Choose two saved cases. Opening a comparison never reruns a model or
        reveals a sealed answer.
      </p>
      <div className="comparison-pickers">
        {[0, 1].map((i) => (
          <label key={i}>
            {i === 0 ? "Run A" : "Run B"}
            <select
              aria-label={i === 0 ? "Comparison run A" : "Comparison run B"}
              value={ids[i]}
              onChange={(e) =>
                setIds((old) =>
                  i === 0 ? [e.target.value, old[1]] : [old[0], e.target.value],
                )
              }
            >
              <option value="">Choose a saved case…</option>
              {cases.map((c) => (
                <option
                  key={c.case_id}
                  value={c.case_id}
                  disabled={ids[1 - i] === c.case_id}
                >
                  {c.title ?? c.case_id} · {c.case_id.slice(-6)} ·{" "}
                  {humanState(c.state)}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {!cases.length && (
        <p className="empty-comparison">
          No saved cases yet. Open a recording in Cases, or create an
          investigation to build a comparison.
        </p>
      )}
      {loading && <p role="status">Reading the two saved runs…</p>}
      {error && (
        <p role="alert" className="bad">
          Could not load this comparison: {error}
        </p>
      )}
      {both && (
        <>
          <p
            className={`comparison-identity ${sameHash ? "same" : "different"}`}
            data-testid="comparison-identity"
          >
            {identity}
          </p>
          <div className="tablewrap">
            <table data-testid="saved-comparison-table">
              <thead>
                <tr>
                  <th>Recorded condition</th>
                  {views.map((v, i) => (
                    <th key={i}>
                      {i === 0 ? "Run A" : "Run B"}
                      <button
                        className="linkish"
                        onClick={() => onOpen(v!.case.case_id)}
                      >
                        {v!.case.title ?? v!.case.case_id} ↗
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ["State", (v: CaseView) => humanState(v.case.state)],
                  [
                    "Origin",
                    (v: CaseView) => originLabel(v.case.labels.evidence_origin),
                  ],
                  [
                    "Inference",
                    (v: CaseView) =>
                      `${v.case.labels.inference_label} · ${v.case.labels.model_id ?? "model not recorded"}`,
                  ],
                  [
                    "Worker choices",
                    (v: CaseView) =>
                      v.case.labels.worker_choices ?? "Not a worker-lab run",
                  ],
                  [
                    "Changed-objective policy",
                    (v: CaseView) =>
                      v.case.labels.changed_objective_policy ??
                      "Not a worker-lab run",
                  ],
                  [
                    "Permission / context",
                    (v: CaseView) =>
                      v.case.lab
                        ? `${v.case.lab.conditions.rogue_permissions} / ${v.case.lab.conditions.context_load}`
                        : "Not recorded",
                  ],
                  [
                    "Investigation mode",
                    (v: CaseView) =>
                      v.case.labels.investigation_mode_label ??
                      v.case.investigation_mode ??
                      "Not recorded",
                  ],
                  [
                    "Evidence hash",
                    (v: CaseView) =>
                      v.manifest?.raw_bundle_sha256 ?? "Not recorded",
                  ],
                  [
                    "Decision requests used / allowed",
                    (v: CaseView) =>
                      `${v.report?.usage?.llm_calls ?? "Not recorded"} / ${v.case.lab?.conditions.investigator_requests ?? "allowance not recorded"}`,
                  ],
                  [
                    "Measured tokens in / out",
                    (v: CaseView) =>
                      v.report?.usage
                        ? `${v.report.usage.tokens_in ?? 0} / ${v.report.usage.tokens_out ?? 0}`
                        : "Not recorded",
                  ],
                  [
                    "Findings / unresolved",
                    (v: CaseView) =>
                      v.report
                        ? `${v.report.findings?.filter((f) => f.category === "incident_allegation").length ?? 0} allegations / ${v.report.findings?.filter((f) => f.category === "unresolved").length ?? 0} unresolved`
                        : "No report",
                  ],
                  [
                    "Observable effects caught",
                    (v: CaseView) =>
                      v.reveal
                        ? ratio(v.reveal.score.step_recall)
                        : v.case.scored === false
                          ? "Unscored import"
                          : "Not revealed",
                  ],
                  [
                    "Benign false allegation",
                    (v: CaseView) =>
                      v.reveal
                        ? String(
                            v.reveal.score.benign_false_alert ??
                              "Not applicable",
                          )
                        : "Not scored",
                  ],
                  [
                    "Estimated run cost",
                    (v: CaseView) =>
                      v.report?.usage?.cost_estimate_usd != null
                        ? `$${v.report.usage.cost_estimate_usd.toFixed(4)}`
                        : "Not recorded",
                  ],
                ].map(([label, read]) => (
                  <tr key={label as string}>
                    <th scope="row">{label as string}</th>
                    {views.map((v, i) => (
                      <td
                        key={i}
                        className={label === "Evidence hash" ? "mono hash" : ""}
                      >
                        {(read as (v: CaseView) => string)(v!)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            A seed does not promise identical model choices. Missing, stopped
            and unscored outcomes stay visible. A source-removal view is a
            different evidence condition, not proof that the original event did
            not happen.
          </p>
        </>
      )}
    </section>
  );
}

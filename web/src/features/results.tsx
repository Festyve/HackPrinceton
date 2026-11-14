import type { PairedSummary } from "../api";
import { CLAIM_TITLES } from "../model";
import { words } from "./operation";

const frac = (r?: { num?: number | null; den?: number | null } | null) =>
  r && r.den ? r.num + "/" + r.den : "n/a";

/** The six systems summed over the declared evaluation suites. Every number comes from the server. */

export function EvaluationSummary({ s }: { s: PairedSummary }) {
  const lost = s.correct_findings_not_counted ?? [];
  const cases = s.suites.reduce((n, x) => n + x.cases, 0);
  return (
    <section className="evaluation" data-testid="evaluation-summary">
      <h2>
        Six systems on {cases} new cases{" "}
        <small className="mono">
          {s.suites.map((x) => x.suite).join(" + ")}
        </small>
      </h2>
      <p className="small muted">
        {s.incident_cases} incident cases and {s.benign_cases} benign controls ·
        simulated evidence ·{" "}
        {s.inference === "LIVE_MODEL" ? "real model runs" : s.inference} on{" "}
        <span className="mono">{s.model}</span> · one run per cell
        {s.verifier_feedback_during_investigation === false &&
          " · no system was told whether a finding was supported while it investigated"}
      </p>
      <div className="tablewrap">
        <table data-testid="evaluation-table">
          <thead>
            <tr>
              <th>System</th>
              <th>Incident effects established</th>
              <th>Cover-ups found</th>
              <th>Benign cases with an accepted allegation</th>
              <th>Runs stopped by a budget cap</th>
              <th>Est. cost</th>
            </tr>
          </thead>
          <tbody>
            {s.systems
              .filter((x) => x.aggregate)
              .map((x) => (
                <tr key={x.id} data-system={x.id}>
                  <td>
                    <b>{x.id}</b>
                    <div className="small muted">{x.label}</div>
                  </td>
                  <td>{frac(x.aggregate?.step_recall)}</td>
                  <td>{frac(x.aggregate?.coverup_detected)}</td>
                  <td>{frac(x.aggregate?.benign_false_alert)}</td>
                  <td>
                    {x.censored} of {x.cells}
                  </td>
                  <td>
                    {x.aggregate?.cost_estimate_usd
                      ? "$" + x.aggregate.cost_estimate_usd.toFixed(2)
                      : "–"}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <p className="note">{s.note}</p>
      {(s.repeats ?? []).map((r) => (
        <details
          className="benchmark-details"
          key={r.repeat.run_id}
          data-testid="evaluation-repeat"
        >
          <summary>
            Run once more on the same evidence: {r.ai_cells_same_effects} of{" "}
            {r.ai_cells} model cells established the same number of effects
          </summary>
          <p className="small muted">
            <span className="mono">{r.repeat.suite}</span> repeats the incident
            cells of <span className="mono">{r.first.suite}</span>. {r.note}
          </p>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>System</th>
                  <th>Effects established, first run</th>
                  <th>Effects established, repeat</th>
                  <th>Runs stopped by a cap, first / repeat</th>
                </tr>
              </thead>
              <tbody>
                {r.per_system.map((x) => (
                  <tr key={x.id} data-system={x.id}>
                    <td>
                      <b>{x.id}</b>
                      <div className="small muted">{x.label}</div>
                    </td>
                    <td>
                      {x.first[0]}/{x.first[1]}
                    </td>
                    <td>
                      {x.repeat[0]}/{x.repeat[1]}
                    </td>
                    <td>
                      {x.stopped_by_a_cap[0]} / {x.stopped_by_a_cap[1]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
      {lost.length > 0 && (
        <details className="benchmark-details">
          <summary>
            {lost.length} correct finding{lost.length === 1 ? "" : "s"} that did
            not count
          </summary>
          <p className="small muted">
            These matched something that happened, but were not accepted in the
            locked report, so they earned nothing.
          </p>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>System</th>
                  <th>Finding</th>
                  <th>Why it did not count</th>
                  <th>What the check said</th>
                </tr>
              </thead>
              <tbody>
                {lost.map((x, i) => (
                  <tr key={i}>
                    <td>{x.case_ref}</td>
                    <td>{x.system_id}</td>
                    <td>{CLAIM_TITLES[x.claim_type] ?? words(x.claim_type)}</td>
                    <td>{words(x.status)}</td>
                    <td>{words(x.check_result)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- environment designer

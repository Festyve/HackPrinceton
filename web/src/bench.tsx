import { useEffect, useState } from "react";
import { api } from "./api";
import type { Benchmark } from "./api";
import { ratio } from "./common";

export function BenchmarkTab() {
  const [b, setB] = useState<Benchmark | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.benchmark().then(setB).catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);
  if (err) return <div className="banner err">{err}</div>;
  if (!b) return <p className="muted">Loading…</p>;
  if (!b.available) return <div className="panel" data-testid="benchmark-unavailable"><h2>Benchmark not available</h2><p>{b.reason ?? "No reason given."}</p></div>;
  const n = (v: number | null | undefined) => (v == null ? "—" : String(v));
  return (
    <div className="bench">
      <h2>Benchmark <small className="mono">{b.suite}</small></h2>
      <p className="small muted">generated {b.generated_at ?? "n/a"} · commit <span className="mono">{b.git_commit ?? "n/a"}</span> · scorer {b.scorer_version ?? "n/a"} · evidence {b.evidence_origin ?? "n/a"}</p>
      {b.ai_pilot && (
        <p className="small" data-testid="benchmark-pilot">
          <b>AI pilot</b> (rows marked LIVE_MODEL): run <span className="mono">{b.ai_pilot.run_id ?? "n/a"}</span> · commit{" "}
          <span className="mono">{b.ai_pilot.git_commit ?? "n/a"}</span> · model{" "}
          <span className="mono">{b.ai_pilot.model_settings?.lead_model ?? "n/a"}</span> · effort {b.ai_pilot.model_settings?.effort ?? "n/a"} ·{" "}
          {b.ai_pilot.system_runs_started ?? "?"} system-runs · 4 cases per system, one run each. A smoke comparison, not a population estimate.
        </p>
      )}
      <div className="tablewrap">
        <table data-testid="benchmark-table">
          <thead><tr><th>ID</th><th>System</th><th>Status</th><th>Cases</th><th>Effects caught</th><th>Raw proposal prec.</th><th>Final prec.</th><th>Cover-ups detected</th><th>Account identified</th><th>Benign final false alerts</th><th>Benign raw alerts</th></tr></thead>
          <tbody>
            {(b.systems ?? []).map((s) => {
              const a = s.aggregate;
              const notRun = s.status === "NOT_RUN" || !a;
              return (
                <tr key={s.id}>
                  <td className="sysid">{s.id}</td>
                  <td><b>{s.label ?? s.id}</b><div className="small muted">{s.inference}{s.model_id ? " · " + s.model_id : ""}</div></td>
                  <td>{notRun ? <b className="amber">{"◌"} {s.status_detail ?? "NOT RUN"}</b> : <b className="ok">{"✓"} {s.status ?? "RUN"}</b>}</td>
                  <td>{s.completed ?? "—"}/{s.n_cases ?? "—"}{s.errors ? ` (${s.errors} errors)` : ""}</td>
                  {notRun ? <td colSpan={7} className="muted">no results: this system has not been run</td> : (
                    <>
                      <td>{ratio(a?.step_recall)}</td><td>{ratio(a?.proposal_precision)} <span className="small muted">of {n(a?.raw_incident_proposals)} raw</span></td><td>{ratio(a?.final_precision)}</td>
                      <td>{ratio(a?.coverup_detected)}</td><td>{ratio(a?.account_identification)}</td><td>{ratio(a?.benign_false_alert)}</td><td>{ratio(a?.benign_raw_alert)}</td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <h3>Per-case runs</h3>
      <div className="tablewrap">
        <table>
          <thead><tr><th>System</th><th>Case</th><th>Status</th><th>Effects caught</th><th>Final precision</th><th>Model calls</th><th>Tokens in / out</th><th>Time</th></tr></thead>
          <tbody>
            {(b.runs ?? []).map((r, i) => {
              const u = r.score?.usage;
              return (
                <tr key={i}><td className="sysid">{r.system_id}</td><td className="mono">{r.case_ref}</td><td>{r.status ?? "—"}</td>
                  <td>{ratio(r.score?.step_recall)}</td><td>{ratio(r.score?.final_precision)}</td>
                  <td>{u ? u.llm_calls ?? 0 : "—"}</td>
                  <td>{u ? `${(u.tokens_in ?? 0).toLocaleString()} / ${(u.tokens_out ?? 0).toLocaleString()}` : "—"}</td>
                  <td>{u?.wall_seconds != null ? `${u.wall_seconds.toFixed(1)} s` : "—"}</td></tr>
              );
            })}
            {(b.runs ?? []).length === 0 && <tr><td colSpan={8} className="muted">No runs recorded.</td></tr>}
          </tbody>
        </table>
      </div>
      {b.notes && b.notes.length > 0 && <><h3>Notes</h3><ul>{b.notes.map((x, i) => <li key={i}>{x}</li>)}</ul></>}
      {b.reproduce && b.reproduce.length > 0 && <><h3>Reproduce</h3><pre className="raw">{b.reproduce.join("\n")}</pre></>}
    </div>
  );
}

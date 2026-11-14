import { useState } from "react";
import { Pip } from "./shell";

const ALLOCATIONS = [
  { id: "80/20", name: "Offense-heavy", rogue: 16, investigator: 4 },
  { id: "50/50", name: "Balanced", rogue: 10, investigator: 10 },
  { id: "20/80", name: "Defense-heavy", rogue: 4, investigator: 16 },
];

/** Configuration draft only. No worker execution endpoint has been published in the plan-branch API. */
export function Lab({ onCases }: { onCases: () => void }) {
  const [allocation, setAllocation] = useState("50/50");
  const [permissions, setPermissions] = useState("export-own-log");
  const chosen = ALLOCATIONS.find((a) => a.id === allocation)!;
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
            Understand what an AI worker did, what survived in the records, and
            what an independent investigator can establish.
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
            <p className="eyebrow">Experiment configuration</p>
            <h3>Decision allocation</h3>
          </div>
          <span className="tag">Configuration preview</span>
        </div>
        <fieldset className="allocation-presets">
          <legend className="sr-only">
            Post-transition decision allocation
          </legend>
          {ALLOCATIONS.map((a) => (
            <label key={a.id} className={allocation === a.id ? "selected" : ""}>
              <input
                type="radio"
                name="allocation"
                value={a.id}
                checked={allocation === a.id}
                onChange={() => setAllocation(a.id)}
              />
              <span>
                <strong>{a.id}</strong>
                <b>{a.name}</b>
                <small>
                  {a.rogue} rogue / {a.investigator} investigator requests
                </small>
              </span>
            </label>
          ))}
        </fieldset>
        <p className="allocation-explanation">
          One unit is one provider request, including retries and specialist
          calls. This 20-request pool allows{" "}
          <b>{chosen.rogue} rogue requests</b> and{" "}
          <b>{chosen.investigator} investigator requests</b>. Setup has a
          separate allowance. These are scheduling limits, not intelligence
          scores.
        </p>
        <details className="advanced-config">
          <summary>Permissions & context · independent controls</summary>
          <div className="config-grid">
            <label>
              Rogue permission profile
              <select
                value={permissions}
                onChange={(e) => setPermissions(e.target.value)}
              >
                <option value="export">Synthetic export only</option>
                <option value="export-own-log">
                  Export + own local-log edits
                </option>
                <option value="export-local">
                  Export + bounded local-artifact edits
                </option>
              </select>
            </label>
            <label>
              Evidence/context load
              <select defaultValue="normal">
                <option value="normal">
                  Normal · exact source/record limits pending
                </option>
                <option value="high" disabled>
                  High · contract pending
                </option>
              </select>
            </label>
          </div>
          <p className="small muted">
            A permission change requires a new execution. Investigator-budget
            comparisons must reuse the exact frozen evidence hash. No host
            paths, trusted collector, credentials or external destinations are
            available to workers.
          </p>
        </details>
        <div
          className="worker-availability"
          role="status"
          data-testid="worker-runtime-unavailable"
        >
          <Pip />
          <div>
            <h3>Worker execution is awaiting its backend contract</h3>
            <p>
              The current server supports real case investigations and saved
              model recordings. It does not yet publish the new worker lifecycle
              or allocation endpoint. These settings are a local draft; no
              worker action or model call has been started.
            </p>
            <button onClick={onCases}>
              Explore working case investigations{" "}
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>
      </div>
      <div className="boundary-note">
        <span aria-hidden="true">⌕</span>
        <p>
          <b>Outside the sandbox.</b> The investigator receives a read-only
          evidence snapshot. Operator-only objectives, transitions and the
          answer key are not investigator knowledge.
        </p>
      </div>
    </section>
  );
}

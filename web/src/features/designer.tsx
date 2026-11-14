import { useState } from "react";
import { api } from "../api";
import type { CaseView, Runtime, ScenarioDesign } from "../api";
import { words, message, useActionToken } from "./operation";

const FIXTURE_WORDS: Record<string, string> = {
  none: "No incident · an ordinary day",
  "inside-job-plain": "Inside job · scripted scenario",
  "inside-job-coverup":
    "Inside job with a removed log line · scripted scenario",
};

/** One bounded design request, a preview a person reads, then offline generation. The model plans no incident. */

export function DesignerDialog({
  runtime,
  mode,
  onCase,
}: {
  runtime: Runtime | null;
  mode: string | null;
  onCase: (view: CaseView) => void;
}) {
  const [design, setDesign] = useState<ScenarioDesign | null>(null);
  const [fixture, setFixture] = useState("none");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [asked, setAsked] = useState(0);
  const tokens = useActionToken();
  const designer = runtime?.capabilities?.scenario_designer?.model; // undefined: status not loaded
  const run = async (
    what: string,
    key: string,
    fn: (clientToken: string) => Promise<void>,
  ) => {
    setBusy(what);
    setErr(null);
    try {
      // retried after a lost response, the same request is not made (or billed) twice
      await fn(tokens.take(key));
      tokens.done();
    } catch (e) {
      tokens.done(e);
      setErr(message(e));
    } finally {
      setBusy(null);
    }
  };
  const usable = !!design?.design;
  return (
    <div className="designer" data-testid="designer">
      <p>
        A model chooses an ordinary working day from fixed options: how busy it
        is, one routine condition and when it happens. It plans no incident and
        writes no step.
      </p>
      <p className="small muted">
        {designer === "CONFIGURED"
          ? "One bounded model response, then the case is generated offline."
          : designer === "BLOCKED"
            ? "No model is configured on this server, so a default environment is returned and labeled as a default."
            : "Whether a model is configured on this server is not known here. The design's own label says where it came from."}
      </p>
      <button
        className="primary"
        data-testid="btn-design-ask"
        disabled={busy !== null}
        onClick={() =>
          run("ask", `design-${asked}`, async (clientToken) => {
            setDesign(await api.design(clientToken));
            setAsked((n) => n + 1); // the next press asks for another design
          })
        }
      >
        {busy === "ask"
          ? "Asking…"
          : design
            ? "Ask for another design"
            : "Ask for a design"}
      </button>
      {design && (
        <section className="design-result" data-testid="design-result">
          <p className="design-label" data-testid="design-label">
            {design.label ?? words(design.status)}
          </p>
          {!usable && (
            <p className="small amber">
              {design.fallback_reason ??
                "This request ended without a design, so no case can be made from it."}
            </p>
          )}
          <ul className="design-preview">
            {(design.preview ?? []).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          {usable && (
            <>
              <label className="small">
                Operator only: what happens in this environment
                <select
                  data-testid="design-fixture"
                  value={fixture}
                  onChange={(e) => setFixture(e.target.value)}
                  disabled={busy !== null}
                >
                  {(design.fixtures ?? ["none"]).map((f) => (
                    <option key={f} value={f}>
                      {FIXTURE_WORDS[f] ?? words(f)}
                    </option>
                  ))}
                </select>
              </label>
              <p className="small muted">
                This choice is yours, never the model's. The case looks the same
                either way until its answer is unsealed.
              </p>
              <button
                data-testid="btn-design-generate"
                disabled={busy !== null}
                onClick={() =>
                  run(
                    "generate",
                    `case-${design.design_id}-${fixture}`,
                    async (clientToken) => {
                      onCase(
                        await api.createFromDesign(
                          design.design_id,
                          fixture,
                          clientToken,
                          mode,
                        ),
                      );
                    },
                  )
                }
              >
                {busy === "generate" ? "Generating…" : "Generate the case"}
              </button>
            </>
          )}
        </section>
      )}
      {err && (
        <p role="alert" className="small bad">
          {err}
        </p>
      )}
    </div>
  );
}

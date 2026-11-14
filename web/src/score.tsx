import type { CaseView } from "./api";
import type { Run } from "./model";
import { ratio, fmtTime } from "./common";
import { Dialog } from "./dialog";
import type { Score } from "./generated/contracts";

const EFF: Record<string, [string, string]> = {
  caught: ["✓", "caught"],
  missed: ["✖", "missed"],
  unobservable: ["◌", "unobservable"],
};
const FND: Record<string, [string, string]> = {
  matched: ["✓", "matched"],
  unsupported: ["✖", "unsupported"],
  duplicate: ["≡", "duplicate"],
  rejected: ["⊘", "rejected"],
  matched_but_not_accepted: ["△", "matched but not accepted"],
  not_an_allegation: ["•", "not an allegation"],
};
const yn = (v: boolean | null | undefined, na?: string | null) =>
  v == null ? `N/A${na ? " (" + na + ")" : ""}` : v ? "yes" : "no";

export function ScoreOverlay({
  view,
  run,
  onClose,
}: {
  view: CaseView;
  run: Run;
  onClose: () => void;
}) {
  const rv = view.reveal;
  if (!rv) return null;
  const s: Score = rv.score;
  const t = rv.truth;
  const u = s.usage ?? run.usage ?? {};
  const eff = s.effect_outcomes ?? [];
  const caught = eff.filter((e) => e.outcome === "caught").length;
  const benign = t.case_kind === "benign" || s.case_kind === "benign";
  return (
    <Dialog title="Answer key unsealed" wide onClose={onClose}>
      <div className="score" data-testid="score-panel">
        <p className="eyebrow">Locked report compared with sealed truth</p>
        <h2>
          {benign
            ? "No incident occurred in this case"
            : `${caught} of ${eff.filter((e) => e.outcome !== "unobservable").length} observable effects caught`}
        </h2>
        <div className="leading-facts">
          <p>
            <b>{eff.filter((e) => e.outcome === "missed").length}</b> observable
            effects missed
          </p>
          <p>
            <b>{eff.filter((e) => e.outcome === "unobservable").length}</b>{" "}
            unobservable effects
          </p>
          <p>
            <b>{s.unsupported_named_attribution ?? 0}</b> unsupported named
            attributions
          </p>
        </div>
        {s.notes && s.notes[0] && <p className="note">{s.notes[0]}</p>}
        <details className="scoring-details">
          <summary>Detailed scoring, tokens & timing</summary>
          <div className="metrics">
            <div>
              <span>Step recall</span>
              <b data-testid="score-recall">{ratio(s.step_recall)}</b>
            </div>
            <div>
              <span>Proposal precision</span>
              <b>{ratio(s.proposal_precision)}</b>
            </div>
            <div>
              <span>Final precision</span>
              <b>{ratio(s.final_precision)}</b>
            </div>
            <div>
              <span>Cover-up detected</span>
              <b>{yn(s.coverup_detected, s.coverup_detected_na_reason)}</b>
            </div>
            <div>
              <span>Account identified correctly</span>
              <b>
                {yn(
                  s.account_identification_correct,
                  s.account_identification_na_reason,
                )}
              </b>
            </div>
            <div>
              <span>Unsupported named attribution</span>
              <b>{s.unsupported_named_attribution ?? 0}</b>
            </div>
            <div>
              <span>Attribution abstained</span>
              <b>{s.attribution_abstained ? "yes" : "no"}</b>
            </div>
            {eff.some((e) => e.outcome === "unobservable") && (
              <section className="unobservable-effects">
                <h3>Unobservable effects</h3>
                <p className="small muted">
                  The available evidence could not establish these effects. They
                  are separate from observable misses.
                </p>
                <ul className="outs">
                  {eff
                    .filter((e) => e.outcome === "unobservable")
                    .map((e) => (
                      <li key={e.effect_id} className="o-unobservable">
                        <b>unobservable</b> · {e.effect_type} {e.description}
                      </li>
                    ))}
                </ul>
              </section>
            )}
            {benign && (
              <div>
                <span>Benign false alert</span>
                <b>{yn(s.benign_false_alert)}</b>
              </div>
            )}
            <div>
              <span>Evidence reference validity</span>
              <b>{ratio(s.evidence_reference_validity)}</b>
            </div>
          </div>
          <p className="small muted">
            Usage: {u.llm_calls ?? 0} llm_calls · {u.tokens_in ?? 0} tokens_in ·{" "}
            {u.tokens_out ?? 0} tokens_out · wall_seconds{" "}
            {u.wall_seconds ?? "n/a"} · scripted_turns {u.scripted_turns ?? 0}
            {view.case.timings && (
              <>
                {" "}
                · generate {view.case.timings.generate_s ?? "n/a"} s ·
                investigate {view.case.timings.investigate_s ?? "n/a"} s
              </>
            )}
          </p>
        </details>
        <div className="two">
          <div>
            <h3>
              Truth effects{" "}
              {!benign && (
                <small>
                  {caught}/
                  {eff.filter((e) => e.outcome !== "unobservable").length}{" "}
                  observable caught
                </small>
              )}
            </h3>
            {eff.length === 0 && <p className="muted">No scorable effects.</p>}
            <ul className="outs">
              {eff
                .filter((e) => e.outcome !== "unobservable")
                .map((e) => {
                  const [g, w] = EFF[e.outcome] ?? ["?", e.outcome];
                  return (
                    <li key={e.effect_id} className={"o-" + e.outcome}>
                      <span aria-hidden>{g}</span> <b>{w}</b>{" "}
                      <span className="mono small">{e.effect_type}</span>{" "}
                      {e.description}
                      {e.finding_id && (
                        <span className="muted small"> by {e.finding_id}</span>
                      )}
                    </li>
                  );
                })}
            </ul>
          </div>
          <div>
            <h3>Locked findings</h3>
            <ul className="outs">
              {(s.finding_outcomes ?? []).map((f) => {
                const [g, w] = FND[f.outcome] ?? ["?", f.outcome];
                return (
                  <li key={f.finding_id} className={"o-" + f.outcome}>
                    <span aria-hidden>{g}</span> <b>{w}</b>{" "}
                    <span className="mono small">{f.finding_id}</span>{" "}
                    <span className="small muted">{f.reason}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>

        {eff.some((e) => e.outcome === "unobservable") && (
          <section className="unobservable-effects">
            <h3>Unobservable effects</h3>
            <p className="small muted">
              The available evidence could not establish these effects. They are
              separate from observable misses.
            </p>
            <ul className="outs">
              {eff
                .filter((e) => e.outcome === "unobservable")
                .map((e) => (
                  <li key={e.effect_id} className="o-unobservable">
                    <b>unobservable</b> · {e.effect_type} {e.description}
                  </li>
                ))}
            </ul>
          </section>
        )}
        {benign && (
          <div className="benign">
            <h3>Benign activity</h3>
            <ul>
              {(t.benign_outcomes ?? []).map((b, i) => (
                <li key={i}>
                  <b>{b.kind}</b> on {b.host} ({b.actor_account ?? "n/a"}):{" "}
                  {b.description}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!benign && (
          <div data-testid="truth-steps">
            <h3>{t.plan_label ?? "Executed adversary steps"}</h3>
            <ol className="steps">
              {(t.steps ?? []).map((st) => (
                <li key={st.step_id} className={"st-" + st.execution_status}>
                  <span aria-hidden>
                    {st.execution_status === "succeeded"
                      ? "✓"
                      : st.execution_status === "failed"
                        ? "✖"
                        : "◐"}
                  </span>{" "}
                  <b>{st.execution_status.toUpperCase()}</b> {st.step_name}
                  {st.attack_id && (
                    <span className="mono small"> {st.attack_id}</span>
                  )}
                  <span className="small muted">
                    {" "}
                    on {st.host} as {st.account_used ?? "n/a"}{" "}
                    {fmtTime(st.t_start)}
                  </span>
                  {st.outcome && <div className="small">{st.outcome}</div>}
                </li>
              ))}
            </ol>
          </div>
        )}
        {t.attribution && !benign && (
          <p>
            <b>True operator:</b> {t.attribution.operator_true ?? "n/a"} {"·"}{" "}
            <b>account used:</b> {t.attribution.account_used ?? "n/a"}
            {t.attribution.account_owner_person && (
              <> (owner {t.attribution.account_owner_person})</>
            )}
            {t.attribution.framed != null && (
              <>
                {" "}
                {"·"} account holder framed:{" "}
                {t.attribution.framed ? "yes" : "no"}
              </>
            )}
          </p>
        )}
      </div>
    </Dialog>
  );
}

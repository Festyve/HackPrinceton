import { useEffect, useState } from "react";
import { api } from "./api";
import type { CaseView, Explanation } from "./api";
import type { Finding } from "./generated/contracts";
import {
  CLAIM_TITLES,
  CATEGORY_WORDS,
  VERIFICATION_WORDS,
  hasReport,
} from "./model";
import type { Run } from "./model";
import { Chips } from "./common";

const HUMAN: Record<string, string> = {
  insufficient_evidence: "not established",
  unknown: "not established",
  not_assessed: "not assessed",
};

export function CenterColumn(p: {
  view: CaseView;
  run: Run;
  busy: string | null;
  reviewMsg: string | null;
  onReview: (d: "accept" | "reject") => void;
  onReveal: () => void;
  onShowScore: () => void;
}) {
  const { view, run } = p;
  const state = view.case.state;
  const report = view.report;
  const findings = report?.findings?.length
    ? report.findings
    : run.findingOrder.map((id) => run.findings[id].finding);
  const ordered = [...findings].sort(
    (a, b) =>
      Number(b.claim_type === "local_log_removal") -
      Number(a.claim_type === "local_log_removal"),
  );
  const attribution = report?.attribution ?? run.attribution;
  const ready = !!report && hasReport(state);
  const nInc = findings.filter(
    (f) => f.category === "incident_allegation",
  ).length;
  return (
    <aside className="col findings" aria-label="Findings">
      <div className="column-title">
        <h2>Findings</h2>
        <span>
          {findings.length
            ? String(findings.length).padStart(2, "0")
            : "Pending"}
        </span>
      </div>
      {ready && (
        <p className="findings-summary">
          {nInc} incident allegation{nInc === 1 ? "" : "s"} ·{" "}
          {findings.length - nInc} explanation
          {findings.length - nInc === 1 ? "" : "s"} / open notes
        </p>
      )}
      {ready && (
        <section className="review" aria-label="Report review">
          <h3>
            {state === "awaiting_review"
              ? "Review this report"
              : "Report locked"}
          </h3>
          {state === "awaiting_review" && (
            <>
              <p className="small">
                Accept or reject to lock these findings before unsealing the
                answer key.
              </p>
              <div className="row">
                <button
                  className="primary"
                  data-testid="btn-accept"
                  disabled={p.busy !== null}
                  onClick={() => p.onReview("accept")}
                >
                  Accept report
                </button>
                <button
                  data-testid="btn-reject"
                  disabled={p.busy !== null}
                  onClick={() => p.onReview("reject")}
                >
                  Reject
                </button>
              </div>
            </>
          )}
          {(state === "report_locked" || state === "scored") && (
            <p className="small">
              Decision: <b>{view.case.review_decision ?? "recorded"}</b>.
              Findings and citations are locked.
            </p>
          )}
          {(state === "report_locked" || state === "scored") && (
            <a
              className="export-link"
              data-testid="report-export"
              href={api.reportExportUrl(view.case.case_id)}
              download
            >
              Download the locked report
            </a>
          )}
          {state === "report_locked" && view.case.scored === false && (
            <p className="small muted">
              Imported evidence has no sealed answer key, so there is nothing to
              unseal.
            </p>
          )}
          {state === "report_locked" && view.case.scored !== false && (
            <button
              className="primary"
              data-testid="btn-unseal"
              disabled={p.busy !== null}
              onClick={p.onReveal}
            >
              Unseal answer key
            </button>
          )}
          {state === "scored" && (
            <button onClick={p.onShowScore}>Compare with answer key</button>
          )}
          <p className="small muted">
            Review does not certify a person's responsibility.
          </p>
          {p.reviewMsg && <p role="alert">{p.reviewMsg}</p>}
        </section>
      )}
      {attribution && (
        <div className="overview-attribution">
          <p>
            Account used: <b>{attribution.account_used ?? "none identified"}</b>
          </p>
          <p>
            Human operator:{" "}
            <b>
              {attribution.human_identity === "supported_named_actor"
                ? "Named attribution — review carefully"
                : (HUMAN[attribution.human_identity ?? "not_assessed"] ??
                  "not assessed")}
            </b>
          </p>
        </div>
      )}
      <div className="finding-list">
        {ordered.map((f, i) => (
          <FindingCard key={f.id} f={f} index={i + 1} />
        ))}
      </div>
      {!findings.length && (
        <p className="muted">
          Findings appear as the investigator submits them. No conclusion has
          been reached.
        </p>
      )}
      {attribution && (
        <section className="attribution" data-testid="attribution-panel">
          <p className="eyebrow">Account ≠ person</p>
          <h3>Attribution boundary</h3>
          <dl>
            <dt>Account used</dt>
            <dd>{attribution.account_used ?? "none identified"}</dd>
            <dt>Human operator</dt>
            <dd>
              {attribution.human_identity === "supported_named_actor"
                ? `${attribution.named_person_accused ?? "named"} — review carefully`
                : (HUMAN[attribution.human_identity ?? "not_assessed"] ??
                  "not assessed")}
            </dd>
          </dl>
          <details>
            <summary>Evidence and limitations</summary>
            <p>{attribution.statement}</p>
            <ul>{attribution.limits?.map((l, i) => <li key={i}>{l}</li>)}</ul>
            <Chips
              ids={[
                ...(attribution.supporting_evidence_ids ?? []),
                ...(attribution.contrary_evidence_ids ?? []),
              ]}
            />
          </details>
        </section>
      )}
      {report?.summary && (
        <details className="open-questions">
          <summary>Full report summary</summary>
          <p>{report.summary}</p>
        </details>
      )}
      {!!report?.open_questions?.length && (
        <details className="open-questions">
          <summary>
            Unresolved questions ({report.open_questions.length})
          </summary>
          <ul>
            {report.open_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </details>
      )}
    </aside>
  );
}

function FindingCard({ f, index }: { f: Finding; index: number }) {
  const cls =
    f.claim_type === "local_log_removal"
      ? "tamper"
      : f.status === "rejected_by_verifier"
        ? "rej"
        : f.status === "verified"
          ? "ver"
          : "unres";
  const observation = f.rationale
    ? (f.rationale.match(/^.*?[.!?](?:\s|$)/)?.[0] ?? f.rationale)
    : "Expand for the cited finding.";
  return (
    <article className={`finding ${cls}`} data-testid={`finding-${f.id}`}>
      <header>
        <span className="finding-number">{String(index).padStart(2, "0")}</span>
        <h3>{CLAIM_TITLES[f.claim_type] ?? f.claim_type.replace(/_/g, " ")}</h3>
      </header>
      <p className="observation">
        {observation.length > 165
          ? observation.slice(0, 162) + "…"
          : observation}
      </p>
      <span className="finding-status">
        {(f.status ?? "proposed").replace(/_/g, " ")} ·{" "}
        {CATEGORY_WORDS[f.category] ?? f.category}
      </span>
      <Chips ids={f.evidence_ids} />
      <details>
        <summary>Rationale & alternatives</summary>
        <p>{f.rationale}</p>
        <p className="small">
          {VERIFICATION_WORDS[f.verification_status ?? "not_checked"] ??
            f.verification_status}
        </p>
        {f.verifier_notes?.map((n, i) => (
          <p key={i} className="small">
            <b>Verifier:</b> {n}
          </p>
        ))}
        {f.skeptic_note && (
          <p className="small">
            <b>Skeptic:</b> {f.skeptic_note}
          </p>
        )}
        {!!f.alternative_explanations?.length && (
          <>
            <h4>Benign alternatives</h4>
            <ul>
              {f.alternative_explanations.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </>
        )}
        {!!f.assumptions?.length && (
          <>
            <h4>Assumptions</h4>
            <ul>
              {f.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </>
        )}
        <p className="small muted">
          {f.host} · {f.t_start} to {f.t_end}
          {f.attack_id ? ` · ATT&CK ${f.attack_id}` : ""}
        </p>
      </details>
    </article>
  );
}

export function Ask({ caseId }: { caseId: string }) {
  const [items, setItems] = useState<Explanation[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cur, setCur] = useState<Explanation | null>(null);
  useEffect(() => {
    let live = true;
    setItems(null);
    setCur(null);
    setErr(null);
    api
      .explanations(caseId)
      .then((r) => live && setItems(r.explanations))
      .catch(
        (e: unknown) =>
          live && setErr(e instanceof Error ? e.message : String(e)),
      );
    return () => {
      live = false;
    };
  }, [caseId]);
  if (err)
    return (
      <p role="status" className="small muted">
        Cited explanations unavailable: {err}
      </p>
    );
  const avail = (items ?? []).filter((x) => x.available);
  if (!avail.length) return null;
  return (
    <section className="explanations">
      <h3>
        Cited explanations <small>Predefined · no model inference</small>
      </h3>
      <div className="row wrap">
        {avail.map((x) => (
          <button
            key={x.key}
            data-testid={`explain-${x.key}`}
            className={cur?.key === x.key ? "on" : ""}
            onClick={() => setCur(x)}
          >
            {x.question}
          </button>
        ))}
      </div>
      {cur && (
        <div data-testid="explain-answer" className="answer">
          <p>{cur.answer}</p>
          <p className="small muted">{cur.label}</p>
          <Chips ids={cur.evidence_ids} />
        </div>
      )}
    </section>
  );
}

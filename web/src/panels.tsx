import { useEffect, useState } from "react";
import { api } from "./api";
import type { CaseView, Explanation, SourceInfoLite } from "./api";
import type { Finding } from "./generated/contracts";
import { CATEGORY_ORDER, CATEGORY_WORDS, CLAIM_TITLES, VERIFICATION_WORDS, hasReport, short, stateIdx } from "./model";
import type { Run } from "./model";
import { Chips, Section } from "./common";

const STAGES = ["generate", "freeze", "normalize", "seal", "investigate"] as const;

function stageInfoText(info: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(info)) {
    if (typeof v === "string" && /sha256|hash/i.test(k)) out.push(`${k.replace(/_sha256|_hash/, "")} ${short(v)}`);
    else if (typeof v === "number") out.push(`${k} ${v}`);
  }
  return out;
}

export function LeftColumn({ view, run }: { view: CaseView; run: Run }) {
  const state = view.case.state;
  const st = stateIdx(state);
  const decided = !!view.case.review_decision || st >= stateIdx("report_locked");
  const sources = (view.manifest?.sources ?? []) as SourceInfoLite[];
  const hosts = new Map<string, SourceInfoLite[]>();
  for (const s of sources) hosts.set(s.host, [...(hosts.get(s.host) ?? []), s]);
  const pipe: Array<{ name: string; status: string; info: string[] }> = STAGES.map((n) => {
    const s = run.stages[n];
    return { name: n, status: s?.status === "done" || (n === "investigate" && st >= stateIdx("awaiting_review")) ? "done" : s?.status === "started" ? "active" : "pending", info: s ? stageInfoText(s.info) : [] };
  });
  pipe.push({ name: "review", status: decided ? "done" : state === "awaiting_review" ? "active" : "pending", info: view.case.review_decision ? [view.case.review_decision] : [] });
  pipe.push({ name: "unseal", status: state === "scored" ? "done" : state === "report_locked" ? "active" : "pending", info: [] });
  const glyph: Record<string, string> = { done: "✓", active: "▶", pending: "○" };
  return (
    <section className="col left">
      <h2>{view.card?.title ?? view.case.title ?? "Case"}</h2>
      {view.card && (
        <>
          <Section title="Audience briefing"><p>{view.card.audience_setup}</p></Section>
          <Section title="Tip given to the investigator"><p>{view.card.tip}</p></Section>
        </>
      )}
      <Section title="Pipeline">
        <ol className="pipe">
          {pipe.map((p) => (
            <li key={p.name} className={p.status}>
              <span className="g" aria-hidden>{glyph[p.status]}</span>
              <b>{p.name}</b> <em>{p.status}</em>
              {p.info.length > 0 && <div className="mono small">{p.info.join(" · ")}</div>}
            </li>
          ))}
        </ol>
      </Section>
      <div className={"keybox " + (state === "scored" ? "open" : "locked")}>
        {state === "scored" ? "\u{1F513} Sealed answer key: revealed" : "\u{1F512} Sealed answer key: locked until unseal"}
      </div>
      <Section title="Hosts and sources">
        {[...hosts.entries()].map(([h, ss]) => (
          <div key={h} className="host">
            <b>{h}</b>
            <ul>
              {ss.map((s) => (
                <li key={s.artifact} className="small">
                  {s.tamper_exposure === "independent_witness"
                    ? <span className="tag witness" title="independent witness">{"◆"} independent witness</span>
                    : <span className="tag local" title="host-local, writable by an adversary in this model">{"◇"} host-local</span>}{" "}
                  <span className="mono">{s.logical_file ?? s.artifact.split("/").slice(1).join("/")}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Section>
    </section>
  );
}

const HUMAN: Record<string, string> = {
  insufficient_evidence: "not established", unknown: "not established", not_assessed: "not assessed",
};

export function CenterColumn(p: {
  view: CaseView; run: Run; busy: string | null; reviewMsg: string | null; inFlight: boolean;
  onReview: (d: "accept" | "reject") => void; onReveal: () => void; onShowScore: () => void;
}) {
  const { view, run } = p;
  const state = view.case.state;
  const report = view.report;
  // Prefer streamed findings during investigation; the report is authoritative once present.
  const findings: Finding[] = report?.findings?.length ? report.findings : run.findingOrder.map((id) => run.findings[id].finding);
  const phases: Record<string, string> = {};
  for (const id of run.findingOrder) phases[id] = run.findings[id].phase;
  const groups = CATEGORY_ORDER.map((c) => findings.filter((f) => f.category === c)).filter((g) => g.length);
  const attribution = report?.attribution ?? run.attribution;
  const usage = report?.usage ?? run.usage;

  const ready = !!report && hasReport(state);
  const nInc = findings.filter((f) => f.category === "incident_allegation").length;
  const clip = (t: string, n: number) => (t.length > n ? t.slice(0, n - 1) + "…" : t);

  const reviewPanel = ready && report && (
    <div className="panel review">
      <h3>Report for review</h3>
      <p className="verdict">
        <b>{nInc}</b> incident allegation{nInc === 1 ? "" : "s"} · <b>{findings.length - nInc}</b> benign explanation{findings.length - nInc === 1 ? "" : "s"}/open note{findings.length - nInc === 1 ? "" : "s"}
        {attribution && (
          <> · account used <b className="mono">{attribution.account_used ?? "none identified"}</b> · human operator{" "}
            <b>{attribution.human_identity === "supported_named_actor" ? "⚠ named" : HUMAN[attribution.human_identity ?? "not_assessed"] ?? "not assessed"}</b></>
        )}
      </p>
      {state === "awaiting_review" && (
        <>
          <div className="row">
            <button className="primary" data-testid="btn-accept" disabled={p.busy !== null} onClick={() => p.onReview("accept")}>Accept report</button>
            <button data-testid="btn-reject" disabled={p.busy !== null} onClick={() => p.onReview("reject")}>Reject</button>
          </div>
          <p className="muted small">Accepting locks the report. It does not certify that anyone is responsible.</p>
        </>
      )}
      {(state === "report_locked" || state === "scored") && (
        <p><b>{"\u{1F512} Report locked"}</b>, decision: <b>{view.case.review_decision ?? "recorded"}</b>{" "}
          <span className="mono small">sha256 {short(report.report_sha256 ?? "") || "(not reported)"}</span></p>
      )}
      {state === "report_locked" && (
        <div className="row">
          <button className="primary" data-testid="btn-unseal" disabled={p.busy !== null} onClick={p.onReveal}>Unseal answer key</button>
        </div>
      )}
      {state === "scored" && <button onClick={p.onShowScore}>Show score</button>}
      {p.reviewMsg && <div className="banner err small">{p.reviewMsg}</div>}
      {report.open_questions && report.open_questions.length > 0 && (
        <details className="small"><summary>Open questions ({report.open_questions.length})</summary>
          <ul>{report.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></details>
      )}
    </div>
  );

  const activity = (
    <>
      {run.todo.length > 0 && (
        <Section title="Plan">
          <ul className="todo">
            {run.todo.map((t, i) => (
              <li key={i} className={t.status}>
                <span aria-hidden>{t.status === "completed" ? "☑" : t.status === "in_progress" ? "▶" : "☐"}</span> {t.text}
                <em> {t.status.replace("_", " ")}</em>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {run.agentOrder.length > 0 && (
        <div className="agents">
          {run.agentOrder.map((a) => {
            const g = run.agents[a];
            return (
              <div key={a} className={"agent " + g.status}>
                <b>{a}</b> <span className="tag">{g.status === "finished" ? "✓ finished" : "▶ working"}</span>
                {g.task && <div className="small" title={g.task}>{clip(g.task, 120)}</div>}
                {g.summary && <div className="small muted">{g.summary}</div>}
              </div>
            );
          })}
        </div>
      )}
      {run.tools.length > 0 && (
        <Section title="Tool activity">
          <ul className="tools">
            {run.tools.map((t) => (
              <li key={t.seq}>
                <span className={t.ok ? "ok" : "bad"} aria-hidden>{t.ok ? "✓" : "✖"}</span>{" "}
                <b className="mono">{t.tool}</b> <span className="muted small">{t.agent}{t.ms != null ? ` · ${t.ms} ms` : ""}</span>
                <div className="small">{t.result_summary}</div>
                <Chips ids={t.evidence_ids} />
              </li>
            ))}
          </ul>
        </Section>
      )}
      {run.notes.length > 0 && (
        <Section title="Case-file notes">
          {run.notes.map((n, i) => <div key={i} className="small"><span className="mono">{n.path}</span><div className="pre">{n.preview}</div></div>)}
        </Section>
      )}
    </>
  );
  const hasActivity = run.todo.length + run.agentOrder.length + run.tools.length + run.notes.length > 0;

  return (
    <section className="col center">
      <h2>Investigation {p.inFlight && <span className="live">{"●"} {state}</span>}</h2>
      {reviewPanel}
      {!ready && activity}

      {groups.length > 0 && <h3 className="big">Findings</h3>}
      {groups.map((g) => (
        <div key={g[0].category}>
          <div className="grouphead">{CATEGORY_WORDS[g[0].category] ?? g[0].category}s</div>
          {g.map((f) => <FindingCard key={f.id} f={f} phase={ready ? undefined : phases[f.id]} />)}
        </div>
      ))}

      {attribution && (
        <div className="panel" data-testid="attribution-panel">
          <h3>Attribution</h3>
          <div className="attr"><span>Account used</span> <b className="mono">{attribution.account_used ?? "none identified"}</b></div>
          <div className={"attr" + (attribution.human_identity === "supported_named_actor" ? " warn" : "")}>
            <span>Human operator</span>{" "}
            <b>{attribution.human_identity === "supported_named_actor"
              ? `⚠ ${attribution.named_person_accused ?? "named"} (named, review carefully)`
              : HUMAN[attribution.human_identity ?? "not_assessed"] ?? "not assessed"}</b>
          </div>
          {attribution.statement && <p>{attribution.statement}</p>}
          {attribution.limits && attribution.limits.length > 0 && (
            <><b className="small">Limits</b><ul className="small">{attribution.limits.map((l, i) => <li key={i}>{l}</li>)}</ul></>
          )}
          <Chips ids={[...(attribution.supporting_evidence_ids ?? []), ...(attribution.contrary_evidence_ids ?? [])]} />
        </div>
      )}

      {report && <Ask caseId={view.case.case_id} />}
      {ready && hasActivity && (
        <details className="activity">
          <summary>Investigation activity: {run.agentOrder.length} agent{run.agentOrder.length === 1 ? "" : "s"}, {run.tools.length} tool call{run.tools.length === 1 ? "" : "s"}</summary>
          {activity}
        </details>
      )}
      {usage && (
        <p className="small muted">
          Usage: {usage.llm_calls ?? 0} model calls · {usage.tokens_in ?? 0} tokens in / {usage.tokens_out ?? 0} out · {usage.tool_calls ?? 0} tool calls
          {(usage.scripted_turns ?? 0) > 0 && <> · {usage.scripted_turns} scripted turns (no model)</>}
          {usage.wall_seconds != null && <> · compute {usage.wall_seconds.toFixed(2)} s</>}
        </p>
      )}
    </section>
  );
}

function FindingCard({ f, phase }: { f: Finding; phase?: string }) {
  const bad = f.status === "rejected_by_verifier" || f.verification_status === "invalid_reference";
  const verified = f.status === "verified";
  const glyph = bad ? "✖" : verified ? "✓" : "▲";
  const cls = f.claim_type === "local_log_removal" ? "tamper" : bad ? "rej" : verified ? "ver" : "unres";
  return (
    <article className={"finding " + cls} data-testid={`finding-${f.id}`}>
      <header>
        <span className="g" aria-hidden>{glyph}</span>
        <b>{CLAIM_TITLES[f.claim_type] ?? f.claim_type}</b>
        <span className="tag">{CATEGORY_WORDS[f.category] ?? f.category}</span>
        {f.attack_id && <span className="tag mono">ATT&amp;CK {f.attack_id}</span>}
      </header>
      <div className="small meta">
        <span>status: <b>{(f.status ?? "proposed").replace(/_/g, " ")}</b></span>
        <span>{VERIFICATION_WORDS[f.verification_status ?? "not_checked"] ?? f.verification_status}</span>
        <span>confidence (uncalibrated): {f.confidence != null ? f.confidence.toFixed(2) : "n/a"}</span>
        {phase && <span className="muted">phase: {phase}</span>}
      </div>
      {f.rationale && <p>{f.rationale}</p>}
      {f.verifier_notes && f.verifier_notes[0] && <p className="small"><b>Verifier:</b> {f.verifier_notes[0]}</p>}
      {f.skeptic_note && <p className="small"><b>Skeptic:</b> {f.skeptic_note}</p>}
      {f.alternative_explanations && f.alternative_explanations.length > 0 && (
        <div className="small"><b>Alternative explanations</b><ul>{f.alternative_explanations.map((a, i) => <li key={i}>{a}</li>)}</ul></div>
      )}
      <Chips ids={f.evidence_ids} />
    </article>
  );
}

function Ask({ caseId }: { caseId: string }) {
  const [items, setItems] = useState<Explanation[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cur, setCur] = useState<Explanation | null>(null);
  useEffect(() => {
    let live = true;
    api.explanations(caseId).then((r) => live && setItems(r.explanations)).catch((e: unknown) => live && setErr(e instanceof Error ? e.message : String(e)));
    return () => { live = false; };
  }, [caseId]);
  if (err) return <p className="small muted">Explanations unavailable: {err}</p>;
  const avail = (items ?? []).filter((x) => x.available);
  if (!avail.length) return null;
  return (
    <div className="panel">
      <h3>Ask the evidence <small>predefined questions, not a chat</small></h3>
      <div className="row wrap">
        {avail.map((x) => (
          <button key={x.key} data-testid={`explain-${x.key}`} className={cur?.key === x.key ? "on" : ""} onClick={() => setCur(x)}>{x.question}</button>
        ))}
      </div>
      {cur && (
        <div data-testid="explain-answer" className="answer">
          <p>{cur.answer}</p>
          <p className="small muted">{cur.label}</p>
          <Chips ids={cur.evidence_ids} />
        </div>
      )}
    </div>
  );
}

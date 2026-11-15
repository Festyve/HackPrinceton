import { useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { CaseInfo, CaseView, Compare, Runtime } from "./api";
import type { Finding } from "./generated/contracts";
import { CLAIM_TITLES, hasReport } from "./model";
import type { Run } from "./model";
import { Chips, EvidenceCtx, hhmmss, ratio } from "./common";
import { Dialog } from "./dialog";
import { useRecordedTrace } from "./trace-api";
import { labApi } from "./lab-api";
import type { OperatorRecord } from "./lab-api";
import { req } from "./api";
import { EvidenceColumn } from "./evidence";
import { Ask } from "./panels";
import { EvidenceInspector, InvestigationTools } from "./investigation";
import type { RawState } from "./investigation";
import { humanState } from "./workbench";
import {
  ExperimentComparison,
  QuestionPanel,
  TemperatureRecords,
} from "./phase2";

/** One concise, accurate provenance label. A recorded run always says so. */
export function modeLabel(c: CaseInfo): string {
  const l = c.labels;
  const model = l.model_id && !/no model/i.test(l.model_id) ? l.model_id : "";
  if (l.inference === "SCRIPTED_FIXTURE")
    return l.playback === "REPLAY"
      ? "Recorded replay · scripted fixture"
      : "Scripted fixture";
  if (l.playback === "REPLAY" || l.inference === "RECORDED_MODEL")
    return `Recorded AI run${model ? " · " + model : ""}`;
  if (l.inference === "LIVE_MODEL")
    return `Live model${model ? " · " + model : ""}`;
  return l.inference_label;
}
export function InvModeLabel({ c }: { c: CaseInfo }) {
  return (
    <span
      className="inv-mode"
      data-testid="mode-label"
      title={c.labels.inference_label}
    >
      {modeLabel(c)}
    </span>
  );
}

const TOOL_TITLES: Record<string, string> = {
  get_case_brief: "Read the case brief",
  check_local_vs_collector: "Compared local log with collector copy",
  check_transfer_sessions: "Checked data transfers against policy",
  submit_finding: "Recorded a finding",
  record_skeptic_verdict: "Recorded the skeptic's verdict",
  submit_attribution: "Stated what can be said about who",
  write_todos: "Plan updated",
  write_file: "Wrote case note",
  edit_file: "Wrote case note",
  read_file: "Read case notes",
};
const nice = (s: string) => {
  const t = s.replace(/[_-]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};
interface Row {
  seq: number;
  kind: "start" | "tool" | "delegation" | "plan" | "note";
  title: string;
  n: number;
}
interface StageEvent {
  t: string | null;
  line_t?: string;
  worker: string;
  kind: "routine" | "unassigned" | "local_record_missing";
  action: string;
}
interface Stage {
  label: string;
  workers?: Array<{ id: string; job?: string }>;
  events: StageEvent[];
}

function useRows(caseId: string, run: Run) {
  const { trace, error } = useRecordedTrace(caseId, run.lastSeq);
  const rows = useMemo(() => {
    const raw: Row[] = [];
    if (trace) {
      for (const s of trace.spans) {
        if (s.kind === "run")
          raw.push({ seq: s.start_seq, kind: "start", title: "Investigation started", n: 1 });
        else if (s.kind === "delegation")
          raw.push({
            seq: s.start_seq,
            kind: "delegation",
            title: `Delegated to ${s.actor.replace(/[_-]+/g, " ")}`,
            n: 1,
          });
        else if (s.tool && !["write_todos", "write_file", "edit_file"].includes(s.tool))
          raw.push({
            seq: s.start_seq,
            kind: "tool",
            title: TOOL_TITLES[s.tool] ?? nice(s.tool),
            n: 1,
          });
      }
      trace.plan.forEach((p, i) => {
        if (i === 0) raw.push({ seq: p.seq, kind: "plan", title: "Wrote a plan", n: 1 });
        else if (p.added.length || p.removed.length)
          raw.push({ seq: p.seq, kind: "plan", title: "Plan updated", n: 1 });
      });
      for (const f of trace.case_file)
        if (/write|edit/.test(f.op))
          raw.push({ seq: f.seq, kind: "note", title: "Wrote case note", n: 1 });
    } else if (error) {
      for (const t of run.tools)
        raw.push({ seq: t.seq, kind: "tool", title: TOOL_TITLES[t.tool] ?? nice(t.tool), n: 1 });
    }
    raw.sort((a, b) => a.seq - b.seq);
    const out: Row[] = [];
    for (const r of raw) {
      const last = out[out.length - 1];
      if (last && last.title === r.title && r.kind === "tool") last.n += 1;
      else out.push({ ...r });
    }
    return out;
  }, [trace, error, run.tools]);
  return { rows, ready: !!trace || !!error };
}

const ROW_ICON: Record<Row["kind"], string> = {
  start: "●",
  tool: "⌕",
  delegation: "⇢",
  plan: "☰",
  note: "✎",
};
const played = (id: string) => {
  try {
    return sessionStorage.getItem("alibi.inv.played." + id) === "1";
  } catch {
    return false;
  }
};
const markPlayed = (id: string) => {
  try {
    sessionStorage.setItem("alibi.inv.played." + id, "1");
  } catch {
    /* private mode */
  }
};

function Recap({ stage }: { stage: Stage }) {
  const times = stage.events
    .map((e) => Date.parse(e.t ?? e.line_t ?? ""))
    .filter((n) => !Number.isNaN(n));
  const t0 = Math.min(...times),
    span = Math.max(1, Math.max(...times) - t0);
  const workers =
    stage.workers?.map((w) => w.id) ??
    [...new Set(stage.events.map((e) => e.worker))];
  return (
    <div className="inv-recap" data-testid="inv-recap">
      {workers.map((w) => (
        <div className="inv-lane" key={w}>
          <span className="inv-lane-name">{w}</span>
          <div className="inv-lane-track">
            {stage.events
              .filter((e) => e.worker === w)
              .map((e, i) => {
                const p = (Date.parse(e.t ?? e.line_t ?? "") - t0) / span;
                return (
                  <i
                    key={i}
                    className={"inv-dot k-" + e.kind}
                    title={`${hhmmss(e.t ?? e.line_t)} · ${e.action.replace(/_/g, " ")}`}
                    style={{ left: `${p * 100}%`, animationDelay: `${p * 2.4}s` }}
                  />
                );
              })}
          </div>
        </div>
      ))}
      <p className="inv-legend">
        <span><i className="inv-dot k-routine" /> Routine</span>
        <span><i className="inv-dot k-unassigned" /> Unassigned action</span>
        <span><i className="inv-dot k-local_record_missing" /> Local record missing</span>
        <span className="inv-recap-label">{stage.label}</span>
      </p>
    </div>
  );
}

const SHORT: Record<string, string> = {
  local_log_removal: "Local log lines removed",
  policy_violating_transfer: "Data copied out",
  data_staging: "Data staged for export",
  timestamp_alteration: "File time altered",
  forwarding_stopped: "Log forwarding stopped",
  second_host_session: "Session from another host",
  sensor_stream_discrepancy: "Sensor records disagree",
  shell_history_gap: "Shell history gap",
  metadata_change: "File metadata changed",
  temperature_excursion: "Temperature out of range",
};
const base = (p?: string | null) => (p ?? "").split("/").pop() || (p ?? "");
const firstSentence = (s?: string) => {
  const t = (s ?? "").match(/^.*?[.!?](?:\s|$)/)?.[0] ?? s ?? "";
  return t.length > 150 ? t.slice(0, 147) + "…" : t;
};
function sentence(f: Finding): string {
  const o = f.object_or_session;
  if (f.claim_type === "local_log_removal")
    return `The collector kept lines that are missing from the host's own ${base(o) || "log"}.`;
  if (f.claim_type === "policy_violating_transfer" && o)
    return `Data left ${f.host} for ${o}, which is not an approved destination.`;
  if (f.claim_type === "data_staging" && o)
    return `${base(o)} was written on ${f.host} just before the transfer.`;
  return firstSentence(f.rationale);
}
function Icon({ type }: { type: string }) {
  const d: Record<string, ReactNode> = {
    local_log_removal: (
      <>
        <path d="M7 3h7l4 4v14H7z" />
        <path d="M10 12h5M10 16h5" />
        <path d="M4 20 20 4" />
      </>
    ),
    policy_violating_transfer: (
      <>
        <path d="M4 14v6h16v-6" />
        <path d="M12 15V4M7 9l5-5 5 5" />
      </>
    ),
    data_staging: (
      <>
        <path d="M4 8l8-4 8 4-8 4z" />
        <path d="M4 8v8l8 4 8-4V8M12 12v8" />
      </>
    ),
  };
  return (
    <svg className="inv-icon" viewBox="0 0 24 24" aria-hidden="true">
      {d[type] ?? (
        <>
          <path d="M12 3 2 20h20z" />
          <path d="M12 10v5M12 17.5v.5" />
        </>
      )}
    </svg>
  );
}

function GapVisual({ caseId, f }: { caseId: string; f: Finding }) {
  const open = useContext(EvidenceCtx);
  const [data, setData] = useState<Compare | null>(null);
  useEffect(() => {
    let live = true;
    if (f.host && f.object_or_session)
      api
        .compare(caseId, f.host, f.object_or_session)
        .then((d) => live && setData(d))
        .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [caseId, f.host, f.object_or_session]);
  const i = data?.rows.findIndex((r) => r.status === "retained_by_collector" && r.collector) ?? -1;
  if (!data || i < 0) return null;
  const row = data.rows[i];
  const near = [...data.rows.slice(0, i)].reverse().find((r) => r.local);
  const missing = data.counts.retained_by_collector ?? 1;
  const text = row.text.replace(/^\d{4}-\d{2}-\d{2}T\S+\s+\S+\s+/, "");
  return (
    <div className="inv-gap" data-testid="compare-row-retained">
      <div className="inv-gap-time">
        {hhmmss(row.ts)} UTC
        {missing > 1 && <span>{missing} lines missing</span>}
      </div>
      <button
        className="inv-gap-side local"
        disabled={!near?.local}
        onClick={() =>
          near?.local &&
          open({ artifact: near.local.artifact, line: near.local.line, eventId: near.local.event_id })
        }
      >
        <span className="inv-gap-head">Local</span>
        <b>✕ Missing</b>
        <span className="inv-gap-void" aria-hidden="true" />
      </button>
      <button
        className="inv-gap-side collector"
        data-testid={`chip-${row.collector!.event_id}`}
        onClick={() =>
          open({
            artifact: row.collector!.artifact,
            line: row.collector!.line,
            eventId: row.collector!.event_id,
          })
        }
      >
        <span className="inv-gap-head">Collector</span>
        <b>✓ Retained</b>
        <span className="inv-gap-line mono">{text}</span>
      </button>
    </div>
  );
}

function ProblemCard({ f, caseId, lead }: { f: Finding; caseId: string; lead?: boolean }) {
  const open = useContext(EvidenceCtx);
  const id = f.evidence_ids?.[0];
  return (
    <article
      className={"inv-problem" + (lead ? " lead" : "")}
      data-testid={`finding-${f.id}`}
    >
      <div className="inv-problem-head">
        <Icon type={f.claim_type} />
        <div>
          <h3>{SHORT[f.claim_type] ?? CLAIM_TITLES[f.claim_type] ?? nice(f.claim_type)}</h3>
          <p>{sentence(f)}</p>
        </div>
        {id && (
          <button
            className="inv-view"
            data-testid={`chip-${id}`}
            onClick={() => open(id)}
          >
            View evidence
          </button>
        )}
      </div>
      {lead && <GapVisual caseId={caseId} f={f} />}
    </article>
  );
}

function Minor({ title, items }: { title: string; items: Finding[] }) {
  if (!items.length) return null;
  return (
    <details className="inv-minor">
      <summary>
        {items.length} {title}
        {items.length === 1 ? "" : "s"}
      </summary>
      {items.map((f) => (
        <div key={f.id} className="inv-minor-row" data-testid={`finding-${f.id}`}>
          <b>{CLAIM_TITLES[f.claim_type] ?? nice(f.claim_type)}</b>
          <span>{firstSentence(f.rationale)}</span>
          <Chips ids={f.evidence_ids?.slice(0, 3)} />
        </div>
      ))}
    </details>
  );
}

const HUMAN: Record<string, string> = {
  insufficient_evidence: "not established",
  unknown: "not established",
  not_assessed: "not assessed",
};

function Findings({ view }: { view: CaseView }) {
  const report = view.report!;
  const all = report.findings ?? [];
  const rejected = (f: Finding) => f.status === "rejected_by_verifier";
  const problems = all
    .filter((f) => f.category === "incident_allegation" && !rejected(f))
    .sort(
      (a, b) =>
        Number(b.claim_type === "local_log_removal") -
        Number(a.claim_type === "local_log_removal"),
    );
  const lead = problems[0]?.claim_type === "local_log_removal" ? problems[0] : null;
  const rest = lead ? problems.slice(1) : problems;
  const benign = all.filter((f) => f.category === "benign_explanation" && !rejected(f));
  const other = all.filter(
    (f) => !problems.includes(f) && !benign.includes(f) && !rejected(f),
  );
  const a = report.attribution;
  return (
    <section className="inv-findings" aria-label="Findings" data-testid="inv-findings">
      <header className="inv-section-head">
        <h2>Findings</h2>
        <span className={problems.length ? "inv-count bad" : "inv-count ok"}>
          {problems.length
            ? `${problems.length} problem${problems.length === 1 ? "" : "s"} found`
            : "No problems found"}
        </span>
      </header>
      {!problems.length && (
        <div className="inv-clean" data-testid="inv-clean">
          <span aria-hidden="true">✓</span>
          <div>
            <h3>No problems found</h3>
            <p>The investigator alleged no incident in this evidence.</p>
          </div>
        </div>
      )}
      {lead && <ProblemCard f={lead} caseId={view.case.case_id} lead />}
      {!!rest.length && (
        <div className="inv-problem-grid">
          {rest.map((f) => (
            <ProblemCard key={f.id} f={f} caseId={view.case.case_id} />
          ))}
        </div>
      )}
      <div className="inv-minors">
        <Minor title="benign explanation" items={benign} />
        <Minor title="unresolved item" items={other} />
        <Minor title="allegation rejected by the verifier" items={all.filter(rejected)} />
        {!!report.open_questions?.length && (
          <details className="inv-minor">
            <summary>{report.open_questions.length} open questions</summary>
            <ul>
              {report.open_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </details>
        )}
        {a && (
          <span className="inv-attribution" data-testid="attribution-panel">
            Account: <b>{a.account_used ?? "none identified"}</b> · Person:{" "}
            <b>
              {a.human_identity === "supported_named_actor"
                ? `${a.named_person_accused ?? "named"} — review carefully`
                : (HUMAN[a.human_identity ?? "not_assessed"] ?? "not assessed")}
            </b>
          </span>
        )}
      </div>
    </section>
  );
}

function Reveal({ view, run }: { view: CaseView; run: Run }) {
  const rv = view.reveal!;
  const s = rv.score,
    t = rv.truth;
  const [op, setOp] = useState<OperatorRecord | null>(null);
  const [opErr, setOpErr] = useState<string | null>(null);
  const eff = s.effect_outcomes ?? [];
  const obs = eff.filter((e) => e.outcome !== "unobservable");
  const caught = obs.filter((e) => e.outcome === "caught").length;
  const benign = t.case_kind === "benign" || s.case_kind === "benign";
  const falseAlarm = benign && s.benign_false_alert === true;
  const pct = benign ? (falseAlarm ? 0 : 1) : obs.length ? caught / obs.length : 0;
  const who = [...new Set((t.steps ?? []).map((x) => x.operator_true).filter(Boolean))];
  const when = (t.steps ?? []).map((x) => x.t_start).filter(Boolean).sort()[0];
  const u = s.usage ?? run.usage ?? {};
  const ring = 2 * Math.PI * 52;
  return (
    <section className="inv-reveal" data-testid="score-panel" aria-label="Results">
      <div className="inv-ring">
        <svg viewBox="0 0 120 120" aria-hidden="true">
          <circle cx="60" cy="60" r="52" className="bg" />
          <circle
            cx="60"
            cy="60"
            r="52"
            className={pct === 1 ? "fg ok" : "fg"}
            strokeDasharray={`${ring * pct} ${ring}`}
          />
        </svg>
        <div>
          <b>{benign ? (falseAlarm ? "✕" : "✓") : `${caught} / ${obs.length}`}</b>
          <span>{benign ? "clean run" : "caught"}</span>
        </div>
      </div>
      <div className="inv-reveal-body">
        <h2>
          {benign
            ? falseAlarm
              ? "Nothing happened, but an incident was alleged"
              : "Nothing happened, nothing alleged"
            : caught === obs.length
              ? "Every real effect was caught"
              : `${obs.length - caught} real effect${obs.length - caught === 1 ? "" : "s"} missed`}
        </h2>
        <p>
          {benign
            ? "No incident occurred in this case."
            : `The locked report matched ${caught} of ${obs.length} observable effects in the sealed record.`}
          {!!s.false_claims_final &&
            ` ${s.false_claims_final} allegation${s.false_claims_final === 1 ? " was" : "s were"} unsupported.`}
        </p>
        {!benign && (
          <ul className="inv-effects">
            {eff.map((e) => (
              <li key={e.effect_id} className={"o-" + e.outcome}>
                <span aria-hidden="true">
                  {e.outcome === "caught" ? "✓" : e.outcome === "missed" ? "✕" : "◌"}
                </span>
                <b>{SHORT[e.effect_type] ?? CLAIM_TITLES[e.effect_type] ?? nice(e.effect_type)}</b>
                <span className="mono">{base(e.object)}</span>
                <em>{e.outcome}</em>
              </li>
            ))}
          </ul>
        )}
        {!benign && !!who.length && (
          <p className="inv-who">
            Changed: <b>{who.join(", ").replace(/worker:/g, "Worker ")}</b>
            {when && <> · first action {hhmmss(when)} UTC</>}
            {t.attribution?.account_used && <> · account {t.attribution.account_used}</>}
          </p>
        )}
        <div className="inv-reveal-actions">
          {view.case.lab && (
            <button
              data-testid="btn-operator-history"
              onClick={() =>
                labApi
                  .operator(view.case.case_id)
                  .then(setOp)
                  .catch((e: unknown) => setOpErr(e instanceof Error ? e.message : String(e)))
              }
            >
              Operator history
            </button>
          )}
          {opErr && <span className="bad small">{opErr}</span>}
        </div>
        <details className="inv-minor scoring-details">
          <summary>Detailed scoring</summary>
          <p className="small">
            Step recall <b data-testid="score-recall">{ratio(s.step_recall)}</b> · final
            precision <b>{ratio(s.final_precision)}</b> · reference validity{" "}
            <b>{ratio(s.evidence_reference_validity)}</b> · cover-up detected{" "}
            <b>
              {s.coverup_detected == null
                ? `N/A${s.coverup_detected_na_reason ? ` (${s.coverup_detected_na_reason})` : ""}`
                : s.coverup_detected
                  ? "yes"
                  : "no"}
            </b>
          </p>
          {s.notes?.[0] && <p className="small">{s.notes[0]}</p>}
          <div data-testid="truth-steps">
            <p className="small">{t.plan_label ?? "Executed steps"}</p>
            <ol className="small">
              {(t.steps ?? []).map((st) => (
                <li key={st.step_id}>
                  <b>{st.execution_status.toUpperCase()}</b> {st.step_name} · {st.host} as{" "}
                  {st.account_used ?? "n/a"} {hhmmss(st.t_start)}
                  {st.outcome && <> — {st.outcome}</>}
                </li>
              ))}
              {(t.benign_outcomes ?? []).map((b, i) => (
                <li key={"b" + i}>
                  <b>{b.kind}</b> on {b.host}: {b.description}
                </li>
              ))}
            </ol>
          </div>
          <ul className="small">
            {(s.finding_outcomes ?? []).map((f) => (
              <li key={f.finding_id}>
                <span className="mono">{f.finding_id}</span> {f.outcome.replace(/_/g, " ")} ·{" "}
                {f.reason}
              </li>
            ))}
          </ul>
          <p className="small muted">
            Usage: {u.llm_calls ?? 0} llm_calls · {u.tokens_in ?? 0} tokens_in ·{" "}
            {u.tokens_out ?? 0} tokens_out · wall_seconds {u.wall_seconds ?? "n/a"}
          </p>
        </details>
      </div>
      {op && (
        <Dialog title="Operator history" wide onClose={() => setOp(null)}>
          <div className="operator-record" data-testid="operator-history">
            <p>{op.label}</p>
            <p>
              {op.transition
                ? `Recorded objective change: ${op.transition.worker} at ${hhmmss(op.transition.t)}, tick ${op.transition.tick}.`
                : "No objective transition was recorded."}
            </p>
            <ol>
              {op.records.map((r) => (
                <li key={r.seq} data-outcome={r.status}>
                  <div>
                    <span className="mono">{hhmmss(r.t)}</span>
                    <b>
                      {r.worker} · {r.action.replace(/_/g, " ")}
                    </b>
                    <span>{r.status.replace(/_/g, " ")}</span>
                  </div>
                  <p>{r.outcome}</p>
                </li>
              ))}
            </ol>
          </div>
        </Dialog>
      )}
    </section>
  );
}

export function InvestigationWorkspace(p: {
  view: CaseView;
  run: Run;
  busy: string | null;
  reviewMsg: string | null;
  raw: RawState | null;
  narrow: boolean;
  runtime: Runtime | null;
  selectedHost: string | null;
  onReview: (d: "accept" | "reject") => void;
  onReveal: () => void;
  onCloseRaw: () => void;
  onSources: () => void;
  onPanel: (d: "plan" | "trace" | "notes") => void;
  onLab: () => void;
}) {
  const { view, run } = p;
  const c = view.case;
  const id = c.case_id;
  const state = c.state;
  const stopped = state === "failed" || state === "cancelled";
  const reported = !!view.report && hasReport(state);
  const { rows, ready } = useRows(id, run);
  const [stage, setStage] = useState<Stage | null>(null);
  const [stageDone, setStageDone] = useState(!c.lab);
  // Playback is local pacing of events the server already recorded; it is skipped once seen.
  const [paced, setPaced] = useState(
    () => !played(id) && state !== "report_locked" && state !== "scored",
  );
  const [recap, setRecap] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [details, setDetails] = useState(false);
  const list = useRef<HTMLOListElement>(null);
  const findingsRef = useRef<HTMLDivElement>(null);
  const reveal = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!c.lab) return;
    let live = true;
    req<Stage>(`/api/cases/${encodeURIComponent(id)}/lab/stage`)
      .then((s) => {
        if (!live) return;
        if (s.events?.length) {
          setStage(s);
          setRecap(true);
        }
        setStageDone(true);
      })
      .catch(() => live && setStageDone(true));
    return () => {
      live = false;
    };
  }, [id, !!c.lab]);
  useEffect(() => {
    if (!recap || !paced) return;
    const t = window.setTimeout(() => setRecap(false), 3200);
    return () => window.clearTimeout(t);
  }, [recap, paced]);

  const inRecap = paced && (!stageDone || recap);
  const shown = paced ? Math.min(cursor, rows.length) : rows.length;
  useEffect(() => {
    if (!paced || inRecap || cursor >= rows.length) return;
    const pace = Math.max(140, Math.min(480, 9000 / Math.max(1, rows.length)));
    const t = window.setTimeout(() => setCursor((n) => n + 1), pace);
    return () => window.clearTimeout(t);
  }, [paced, inRecap, cursor, rows.length]);
  const done = reported && (!paced || (ready && !inRecap && cursor >= rows.length));
  useEffect(() => {
    if (!done) return;
    markPlayed(id);
    if (paced) {
      setPaced(false);
      window.setTimeout(
        () => findingsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
        60,
      );
    }
  }, [done, id, paced]);
  useEffect(() => {
    const el = list.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown, expanded]);
  useEffect(() => {
    if (state === "scored" && view.reveal)
      reveal.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [state, !!view.reveal]);

  const phase = done ? 3 : inRecap ? 1 : 2;
  const waiting = !reported && !stopped && shown >= rows.length;
  const delegations = rows.filter((r) => r.kind === "delegation").length;
  const revisions = rows.filter((r) => r.title === "Plan updated").length;
  const notes = rows.filter((r) => r.kind === "note").length;
  const steps = rows.reduce((n, r) => n + r.n, 0);
  const showList = !done || expanded;
  const tools = (
    <InvestigationTools
      hasCase
      planProgress={
        run.todo.length
          ? `${run.todo.filter((t) => t.status === "completed").length}/${run.todo.length}`
          : undefined
      }
      onSources={p.onSources}
      onPlan={() => p.onPanel("plan")}
      onCaseFile={() => p.onPanel("notes")}
      onTrace={() => p.onPanel("trace")}
      onQuestions={() => {
        const more = document.querySelector<HTMLDetailsElement>(".inv-more");
        if (more) more.open = true;
        document.querySelector<HTMLInputElement>("#case-question")?.focus();
      }}
    />
  );
  return (
    <div className="inv" data-phase={phase}>
      <section className="inv-card inv-activity" data-testid="inv-activity" aria-label="Activity">
        <header className="inv-section-head">
          <h2>Activity</h2>
          <ol className="inv-stepper" aria-label="Activity phases">
            {stage && <li className={phase === 1 ? "on" : "past"}>Sandbox recap</li>}
            <li className={phase === 2 ? "on" : phase > 2 ? "past" : ""}>Investigator at work</li>
            <li className={phase === 3 ? "on" : ""}>Findings</li>
          </ol>
          <span className="statepill" data-testid="case-state">
            {humanState(state)}
          </span>
          {!done && !stopped && (
            <button
              className="inv-skip"
              data-testid="btn-skip"
              onClick={() => {
                setPaced(false);
                setRecap(false);
                markPlayed(id);
              }}
              disabled={!paced}
            >
              Skip to findings
            </button>
          )}
          <button
            className="linkish inv-details-link"
            data-testid="btn-inv-details"
            aria-expanded={details}
            onClick={() => setDetails((v) => !v)}
          >
            Details
          </button>
        </header>
        {details && tools}
        {done && (
          <button
            className="inv-summary"
            data-testid="inv-activity-summary"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            <span className="ok">✓</span>
            <span>
              Investigation complete · {steps} recorded step{steps === 1 ? "" : "s"}
              {delegations ? ` · ${delegations} delegation${delegations === 1 ? "" : "s"}` : ""}
              {revisions ? ` · plan updated ${revisions}×` : ""}
              {notes ? ` · ${notes} case note${notes === 1 ? "" : "s"}` : ""}
            </span>
            <span className="inv-summary-toggle">{expanded ? "Hide timeline" : "Show timeline"}</span>
          </button>
        )}
        {stage && (inRecap || (done && expanded)) && <Recap stage={stage} />}
        {showList && !inRecap && (
          <ol className="inv-rows" ref={list} data-testid="inv-rows">
            {rows.slice(0, shown).map((r) => (
              <li key={r.seq} data-kind={r.kind}>
                <span className="inv-row-icon" aria-hidden="true">
                  {ROW_ICON[r.kind]}
                </span>
                <span>{r.title}</span>
                {r.n > 1 && <span className="inv-row-n">×{r.n}</span>}
              </li>
            ))}
            {waiting && (
              <li className="inv-waiting" role="status">
                <span className="inv-spinner" aria-hidden="true" />
                Investigator still working…
              </li>
            )}
            {stopped && (
              <li className="inv-stopped" role="status">
                Investigation ended before review
                {(c.error || run.error) && <span> · {c.error || run.error}</span>}
              </li>
            )}
          </ol>
        )}
      </section>

      {done && (
        <div ref={findingsRef} className="inv-anchor">
          {c.parent_case_id && <ExperimentComparison view={view} />}
          <Findings view={view} />
        </div>
      )}
      {done && state === "scored" && view.reveal && (
        <div ref={reveal} className="inv-anchor">
          <Reveal view={view} run={run} />
        </div>
      )}
      {done && (
        <div className="inv-actionbar" role="group" aria-label="Report review">
          {state === "awaiting_review" && (
            <>
              <button
                className="primary inv-primary"
                data-testid="btn-accept"
                disabled={p.busy !== null}
                onClick={() => p.onReview("accept")}
              >
                Lock report
              </button>
              <button
                className="linkish"
                data-testid="btn-reject"
                disabled={p.busy !== null}
                onClick={() => p.onReview("reject")}
              >
                Reject
              </button>
            </>
          )}
          {state === "report_locked" && c.scored !== false && (
            <button
              className="primary inv-primary"
              data-testid="btn-unseal"
              disabled={p.busy !== null}
              onClick={p.onReveal}
            >
              Reveal results
            </button>
          )}
          {(state === "report_locked" || state === "scored") && (
            <span className="inv-locked">
              Report locked · {c.review_decision ?? "recorded"}
              {state === "report_locked" && c.scored === false && " · imported evidence has no sealed answer"}
            </span>
          )}
          {p.reviewMsg && <span role="alert" className="bad">{p.reviewMsg}</span>}
        </div>
      )}

      {done && (
        <details className="inv-more" data-testid="inv-more">
          <summary>More tools</summary>
          {tools}
          {(state === "report_locked" || state === "scored") && (
            <a
              className="export-link"
              data-testid="report-export"
              href={api.reportExportUrl(id)}
              download
            >
              Download the locked report
            </a>
          )}
          {c.lab && (
            <div className="inv-lab-context" data-testid="worker-provenance">
              <span>
                {c.labels.investigation_mode_label} · {c.labels.worker_choices}
              </span>
              <span>{c.labels.changed_objective_policy}</span>
              <button className="linkish" onClick={p.onLab}>
                Inspect workers & activity ↗
              </button>
            </div>
          )}
          {view.report?.summary && <p className="small">{view.report.summary}</p>}
          <Ask caseId={id} />
          <QuestionPanel caseId={id} available={!!view.report} runtime={p.runtime} />
          {c.card_id === "cold-chain" && (
            <TemperatureRecords caseId={id} stateKey={view.manifest?.bundle_id ?? ""} />
          )}
          <EvidenceColumn caseId={id} view={view} run={run} selectedHost={p.selectedHost} />
        </details>
      )}
      {p.raw && !p.narrow && <EvidenceInspector raw={p.raw} onClose={p.onCloseRaw} />}
    </div>
  );
}

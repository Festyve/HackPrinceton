// Second-run features wired to their real endpoints: questions, source-removal experiments,
// the spend estimate and the two temperature records of a cold-chain case.
// Every label shown here (support, change, inference) is decided by the server.
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, token } from "./api";
import type {
  CaseView,
  ExcludedSource,
  ExperimentClaim,
  PairedSummary,
  QuestionAnswer,
  Runtime,
  ScenarioDesign,
  SensorPoint,
  SensorStreams,
  SourceExperiment,
  Spend,
} from "./api";
import { Chips, EvidenceCtx, hhmmss } from "./common";
import { CLAIM_TITLES, hasReport } from "./model";

const words = (s: string) => s.replace(/_/g, " ");
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
/** The request may have reached the server although no response came back. */
const lostResponse = (e: unknown) => e instanceof ApiError && e.status === 0;

/**
 * One idempotency token per distinct action. The same action retried after a lost response sends the same
 * token, so the server returns what it already made instead of making (and, for a model, billing) a second one.
 * Once the server has answered or refused, the next attempt is a new action with a new token.
 */
function useActionToken() {
  const held = useRef<{ key: string; token: string } | null>(null);
  return useMemo(
    () => ({
      take(key: string): string {
        if (held.current?.key !== key) held.current = { key, token: token() };
        return held.current.token;
      },
      done(error?: unknown) {
        if (!lostResponse(error)) held.current = null;
      },
    }),
    [],
  );
}

// --------------------------------------------------------------------------- questions

const SUPPORT: Record<string, string> = {
  checked: "Confirmed by a check",
  contradicted: "Contradicted by a check",
  cited: "Cited · not machine-checked",
  interpretation: "Model's interpretation",
  unsupported: "Unsupported",
};
const ANSWER_STATUS: Record<string, string> = {
  pending: "Answering",
  answered: "Answered",
  insufficient_evidence: "Evidence insufficient",
  unavailable: "Not answered",
  failed: "No answer",
};

function Answer({
  a,
  open,
  unknown,
  onToggle,
  onRefresh,
}: {
  a: QuestionAnswer;
  open: boolean;
  unknown: boolean;
  onToggle: (open: boolean) => void;
  onRefresh: () => void;
}) {
  const limits = a.limitations ?? [];
  const plain = a.status === "unavailable" || a.status === "failed";
  const lost = unknown && a.status === "pending";
  return (
    <details
      className="qa-answer"
      open={open}
      onToggle={(e) => {
        if (e.currentTarget.open !== open) onToggle(e.currentTarget.open);
      }}
      data-testid="question-answer"
      data-status={a.status}
    >
      <summary>
        <b>{a.question}</b>
        <span className="tag">
          {a.inference_label ?? words(a.inference_mode)}
        </span>
        <span className="tag">
          {lost ? "Status unknown" : (ANSWER_STATUS[a.status] ?? words(a.status))}
        </span>
      </summary>
      {a.status === "pending" && !lost && (
        <p role="status" className="small muted">
          Answering from this case's evidence. At most three model calls.
        </p>
      )}
      {lost && (
        <p role="alert" className="small amber">
          The server could not be reached for this question's status, so it is
          not known whether it was answered.{" "}
          <button className="linkish" data-testid="btn-question-refresh" onClick={onRefresh}>
            Check again
          </button>
        </p>
      )}
      {a.answer && <p className="qa-text">{a.answer}</p>}
      {plain && limits[0] && <p className="qa-text">{limits[0]}</p>}
      {a.error && <p className="small bad">{a.error}</p>}
      {!!a.claims?.length && (
        <ul className="qa-claims">
          {a.claims.map((c, i) => (
            <li key={i} data-support={c.support}>
              <span className={`support ${c.support}`}>
                {SUPPORT[c.support] ?? words(c.support)}
              </span>
              <span>{c.text}</span>
              <Chips ids={c.evidence_ids} />
              {c.basis && <small className="muted">{c.basis}</small>}
            </li>
          ))}
        </ul>
      )}
      {!plain && limits.length > 0 && (
        <details className="qa-limits">
          <summary>
            {limits.length} stated limit{limits.length === 1 ? "" : "s"}
          </summary>
          <ul>
            {limits.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </details>
      )}
      {!!a.follow_up_evidence?.length && (
        <p className="small muted">
          Evidence that would help: {a.follow_up_evidence.join("; ")}
        </p>
      )}
    </details>
  );
}

export function QuestionPanel({
  caseId,
  available,
  runtime,
}: {
  caseId: string;
  available: boolean;
  runtime: Runtime | null;
}) {
  const [items, setItems] = useState<QuestionAnswer[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Saved answers load closed so they do not cover the evidence; the one just asked opens.
  const [openId, setOpenId] = useState<string | null>(null);
  // questions whose status could not be refreshed: shown as unknown, never as still answering
  const [unknown, setUnknown] = useState<string[]>([]);
  const alive = useRef(0);
  const ask = useActionToken();

  const put = useCallback((a: QuestionAnswer) => {
    setItems((cur) =>
      cur.some((x) => x.question_id === a.question_id)
        ? cur.map((x) => (x.question_id === a.question_id ? a : x))
        : [...cur, a],
    );
  }, []);

  /**
   * Poll one pending question until the server gives it a final status. A failed request is retried with a
   * growing pause. If the server stays unreachable, or five minutes pass, the question is marked "status
   * unknown": it is never left looking as if it were still being answered.
   */
  const follow = useCallback(
    async (a: QuestionAnswer, gen: number) => {
      let cur = a;
      let failures = 0;
      const giveUpAt = Date.now() + 5 * 60_000;
      const id = a.question_id;
      setUnknown((u) => u.filter((x) => x !== id));
      while (cur.status === "pending") {
        if (failures >= 6 || Date.now() > giveUpAt) {
          setUnknown((u) => (u.includes(id) ? u : [...u, id]));
          return;
        }
        const pause = Math.min(1500 * 2 ** failures, 12_000);
        await new Promise((r) => window.setTimeout(r, pause));
        if (gen !== alive.current) return;
        try {
          cur = await api.question(caseId, id);
          failures = 0;
        } catch {
          failures += 1;
          continue;
        }
        if (gen !== alive.current) return;
        put(cur);
      }
    },
    [caseId, put],
  );

  /** What the server has for this case, and follow whichever question is still pending. */
  const load = useCallback(
    async (gen: number) => {
      const r = await api.questions(caseId);
      if (gen !== alive.current) return;
      setItems(r.questions);
      const pending = r.questions.find((x) => x.status === "pending");
      if (pending) {
        setBusy(true);
        try {
          await follow(pending, gen);
        } finally {
          if (gen === alive.current) setBusy(false);
        }
      }
    },
    [caseId, follow],
  );

  useEffect(() => {
    const gen = ++alive.current;
    setItems([]);
    setErr(null);
    setText("");
    setBusy(false);
    setOpenId(null);
    setUnknown([]);
    ask.done();
    if (!available) return;
    load(gen).catch((e: unknown) => gen === alive.current && setErr(message(e)));
    return () => {
      alive.current += 1;
    };
  }, [caseId, available, load, ask]);

  const submit = async () => {
    const question = text.trim();
    if (!question || busy || !available) return;
    const gen = alive.current;
    setBusy(true);
    setErr(null);
    try {
      // the same text sent again after a lost response is the same question, not a second one
      const a = await api.ask(caseId, question, ask.take(question));
      if (gen !== alive.current) return;
      ask.done();
      put(a);
      setOpenId(a.question_id);
      setText("");
      await follow(a, gen);
    } catch (e) {
      if (gen !== alive.current) return;
      ask.done(e);
      // The server's own words. A refusal can mean another question is pending, the case's question limit,
      // or a case state that does not take questions; this panel does not guess which.
      setErr(message(e));
      try {
        await load(gen); // show what the server actually has, including a question asked from elsewhere
      } catch {
        /* the first error stays on screen */
      }
    } finally {
      if (gen === alive.current) setBusy(false);
    }
  };

  const caps = runtime?.capabilities?.questions;
  const max = caps?.max_question_chars ?? 1000;
  const model = caps?.model_answers; // undefined when the server's status could not be loaded
  const reason = !available
    ? "Questions become available after the report is drafted."
    : busy
      ? "Answering from this case's evidence…"
      : model === "CONFIGURED"
        ? "A model answers from this case's evidence only. Each claim carries a label saying whether a check confirmed it. A question never changes the report."
        : model === "BLOCKED"
          ? "No model is configured on this server, so a question is recorded and returned unanswered. The cited explanations need no model."
          : "Whether a model is configured on this server is not known here. A question is sent, and its answer says whether a model answered it.";
  return (
    <section className="qa" aria-label="Questions" data-testid="question-composer">
      {items.length > 0 && (
        <div className="qa-answers" data-testid="question-answers">
          <p className="eyebrow">
            {items.length} question{items.length === 1 ? "" : "s"} asked about
            this case · kept apart from the report
          </p>
          {items.map((a) => (
            <Answer
              key={a.question_id}
              a={a}
              open={a.question_id === openId}
              unknown={unknown.includes(a.question_id)}
              onRefresh={() => {
                const gen = alive.current;
                setBusy(true);
                follow(a, gen).finally(() => gen === alive.current && setBusy(false));
              }}
              onToggle={(o) =>
                setOpenId((cur) =>
                  o ? a.question_id : cur === a.question_id ? null : cur,
                )
              }
            />
          ))}
        </div>
      )}
      <form
        className="questions"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div>
          <label htmlFor="case-question">Ask about this evidence</label>
          <p id="question-reason" role={err ? "alert" : undefined}>
            {err ?? reason}
          </p>
        </div>
        <div className="composer">
          <input
            id="case-question"
            type="text"
            value={text}
            maxLength={max}
            onChange={(e) => setText(e.target.value)}
            placeholder="What can these records establish?"
            disabled={!available || busy}
            aria-describedby="question-reason"
          />
          <button
            type="submit"
            data-testid="btn-ask"
            disabled={!available || busy || !text.trim()}
          >
            {busy ? "Answering…" : "Ask"}
          </button>
        </div>
      </form>
    </section>
  );
}

// --------------------------------------------------------------------------- remove a witness

const KIND_WORDS: Record<string, string> = {
  collector: "Log collector",
  flow: "Network tap",
  badge: "Badge reader",
  reference: "Reference temperature logger",
  sensor: "Stored sensor readings",
  auth: "Login records",
  syslog: "System log",
  app: "Records application log",
  mqtt: "Message broker log",
  shell_history: "Shell history",
  fs_stat: "File metadata",
};
const kindWord = (k: string) => KIND_WORDS[k] ?? words(k);
const withheldWords = (xs: ExcludedSource[] | undefined) =>
  [...new Set((xs ?? []).map((x) => kindWord(x.source).toLowerCase()))].join(
    ", ",
  ) || "one source";

export function WitnessPanel({
  view,
  onOpenCase,
}: {
  view: CaseView;
  onOpenCase: (caseId: string) => void;
}) {
  const id = view.case.case_id;
  const parent = view.case.parent_case_id ?? null;
  const sources = view.manifest?.sources ?? [];
  const [exp, setExp] = useState<SourceExperiment | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const deriving = useActionToken();
  const kinds = useMemo(() => {
    const by = new Map<string, { ids: string[]; witness: boolean }>();
    for (const s of sources) {
      const k = by.get(s.source) ?? { ids: [], witness: false };
      if (s.source_id) k.ids.push(s.source_id);
      k.witness = k.witness || s.tamper_exposure === "independent_witness";
      by.set(s.source, k);
    }
    return [...by.entries()]
      .filter(([, v]) => v.ids.length > 0)
      .sort((a, b) => Number(b[1].witness) - Number(a[1].witness));
  }, [sources]);
  const [kind, setKind] = useState("");
  const chosen = kinds.find(([k]) => k === kind) ?? kinds[0];

  useEffect(() => {
    let live = true;
    setExp(null);
    setErr(null);
    if (!sources.length) return;
    api
      .sourceExperiment(id)
      .then((r) => live && setExp(r))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [id, sources.length, view.case.state]);

  if (parent) {
    const n = (view.case.excluded_sources ?? []).length;
    // the server says so when the original was reset; then nothing here may claim it is unchanged or openable
    const gone = exp?.role === "derived" && exp.comparison == null && !!exp.note;
    return (
      <section className="source-experiment" data-testid="source-experiment">
        <h4>Evidence view without the {withheldWords(view.case.excluded_sources)}</h4>
        <p className="small muted">
          Derived from another case with {n} file{n === 1 ? "" : "s"} withheld.{" "}
          {gone
            ? exp?.note
            : "Deriving this view did not change the original evidence or its report."}
        </p>
        {!gone && (
          <button data-testid="btn-open-original" onClick={() => onOpenCase(parent)}>
            Open the original case
          </button>
        )}
      </section>
    );
  }

  const ready = hasReport(view.case.state) && !!view.report && !!chosen;
  const derive = async () => {
    if (!chosen || busy) return;
    setBusy(true);
    setErr(null);
    try {
      // the same choice retried after a lost response returns the derived case that was already made
      const made = await api.createSourceExperiment(
        id,
        chosen[1].ids,
        deriving.take(chosen[0]),
      );
      deriving.done();
      onOpenCase(made.child_case_id);
    } catch (e) {
      deriving.done(e);
      setErr(message(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="source-experiment" data-testid="source-experiment">
      <h4>Remove a witness</h4>
      <p className="small muted">
        Derive a copy of this case without one source, and see which conclusions
        keep their support. The original evidence is not changed.
      </p>
      {kinds.length > 0 && (
        <label className="small">
          Source to withhold
          <select
            data-testid="witness-select"
            value={chosen?.[0] ?? ""}
            onChange={(e) => setKind(e.target.value)}
            disabled={busy}
          >
            {kinds.map(([k, v]) => (
              <option key={k} value={k}>
                {kindWord(k)}
                {v.witness ? " · independent" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      <button data-testid="btn-derive" disabled={!ready || busy} onClick={derive}>
        {busy ? "Deriving…" : "Derive the reduced view"}
      </button>
      {!ready && (
        <p className="small muted">Available once a report has been drafted.</p>
      )}
      {err && (
        <p role="alert" className="small bad">
          {err}
        </p>
      )}
      {!!exp?.children?.length && (
        <ul className="derived-list" data-testid="derived-cases">
          {exp.children.map((c) => (
            <li key={c.child_case_id}>
              <button className="linkish" onClick={() => onOpenCase(c.child_case_id)}>
                Without the {withheldWords(c.excluded_sources)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const CHANGE: Record<ExperimentClaim["change"], { word: string; cls: string }> = {
  retains_support: { word: "Still supported", cls: "retains" },
  loses_support: {
    word: "Cannot be established from this evidence",
    cls: "loses",
  },
  never_supported: {
    word: "Was not supported in the original either",
    cls: "never",
  },
};

/** For a derived case: the original report's claims, re-checked by the server against the reduced evidence. */
export function ExperimentComparison({ view }: { view: CaseView }) {
  const id = view.case.case_id;
  const [exp, setExp] = useState<SourceExperiment | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setExp(null);
    setErr(null);
    api
      .sourceExperiment(id)
      .then((r) => live && setExp(r))
      .catch((e: unknown) => live && setErr(message(e)));
    return () => {
      live = false;
    };
  }, [id]);
  if (err)
    return (
      <div className="banner err small" role="alert">
        The comparison with the original case is unavailable: {err}
      </div>
    );
  const cmp = exp?.comparison;
  if (!exp) return null;
  if (!cmp)
    return (
      <section className="panel experiment" data-testid="experiment-comparison">
        <div className="column-title">
          <h2>What the original report can still establish</h2>
          <span>Not available</span>
        </div>
        <p className="small amber">
          {exp.note ??
            "The server returned no comparison with the original case for this evidence view."}
        </p>
      </section>
    );
  const claims = cmp.claims ?? [];
  const s = cmp.summary;
  return (
    <section className="panel experiment" data-testid="experiment-comparison">
      <div className="column-title">
        <h2>What the original report can still establish</h2>
        <span>Deterministic re-check · no model</span>
      </div>
      <p className="small">
        Withheld: {withheldWords(exp.excluded_sources)}.{" "}
        {exp.events_remaining?.toLocaleString()} of{" "}
        {exp.events_original?.toLocaleString()} records remain.
        {s &&
          ` ${s.retains_support ?? 0} of ${s.claims_total ?? claims.length} original claims keep their support; ${s.loses_support ?? 0} cannot be established here.`}
      </p>
      {!claims.length && (
        <p className="small muted">
          The original case has no drafted report to compare with.
        </p>
      )}
      <ul className="experiment-claims">
        {claims.map((c) => (
          <li key={c.finding_id} data-change={c.change}>
            <span className={`change ${CHANGE[c.change]?.cls ?? ""}`}>
              {CHANGE[c.change]?.word ?? words(c.change)}
            </span>
            <b>
              {CLAIM_TITLES[c.claim_type] ?? words(c.claim_type)}
              {c.object_or_session ? ` · ${c.object_or_session}` : ""}
            </b>
            {c.reason && <span className="small">{c.reason}</span>}
            <Chips ids={c.evidence_ids_remaining} />
          </li>
        ))}
      </ul>
      {cmp.attribution?.child_statement && (
        <p className="small">
          Attribution: {cmp.attribution.child_statement}{" "}
          <span className="muted">{cmp.attribution.note}</span>
        </p>
      )}
      {s?.reading && <p className="small muted">{s.reading}</p>}
    </section>
  );
}

// --------------------------------------------------------------------------- spend

const usd = (v?: number) => (v == null ? "?" : `$${v.toFixed(2)}`);

export function SpendLine() {
  const [s, setS] = useState<Spend | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .spend()
      .then((r) => live && setS(r))
      .catch(() => live && setErr(true));
    return () => {
      live = false;
    };
  }, []);
  return (
    <p className="small muted" data-testid="spend-line">
      {err
        ? "The spend estimate could not be loaded from this server."
        : !s
          ? "Loading the spend estimate…"
          : !s.configured
            ? "No billed model route is configured on this server, so nothing can be spent. Recorded usage belongs to the saved run."
            : s.readable === false
              ? s.note
              : `Estimated model spend ${usd(s.spent_usd)} of the ${usd(s.cap_usd)} allowance across ${s.calls ?? 0} calls; automatic calls stop at ${usd(s.limit_in_force_usd)}. A conservative estimate at list prices, not a bill.`}
    </p>
  );
}

// --------------------------------------------------------------------------- two temperature records

const W = 640;
const H = 250;
const M = { l: 38, r: 14, t: 26, b: 26 };
const PLOT_L = M.l;
const PLOT_R = W - M.r;
const ms = (s: string) => Date.parse(s);
const clampX = (x: number) => Math.min(PLOT_R, Math.max(PLOT_L, x));

function nearest(points: SensorPoint[], t: number): SensorPoint | null {
  let best: SensorPoint | null = null;
  let d = Infinity;
  for (const p of points) {
    const x = Math.abs(ms(p.ts) - t);
    if (x < d) {
      d = x;
      best = p;
    }
  }
  return best;
}

// The headline says no more than the server's status does. "consistent" means the check found no
// disagreement of two or more consecutive readings; single differing readings are counted beside it.
const TEMP_HEADLINE: Record<string, string> = {
  discrepancy_unexplained:
    "The two records disagree, and no stated maintenance explains it.",
  discrepancy_explained:
    "No unexplained disagreement was found. The records differ inside a stated maintenance window.",
  consistent: "No unexplained disagreement was found between the two records.",
};
const DISCREPANCY: Record<string, string> = {
  unexplained: "Unexplained",
  explained_maintenance: "Inside a maintenance window",
  isolated_reading: "A single reading",
};
const EXPOSURE: Record<string, string> = {
  independent_witness: "independent witness",
  host_local_writable: "local record, writable on its host",
};
const HOUR = 3600_000;
const TICK_STEPS = [0.25, 0.5, 1, 2, 3, 6, 12, 24, 48, 96, 168].map((h) => h * HOUR);

export function TemperatureRecords({
  caseId,
  stateKey,
}: {
  caseId: string;
  stateKey: string;
}) {
  const [data, setData] = useState<SensorStreams | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // pointer: a time. keyboard: an index into the series being stepped through, so two readings with the
  // same timestamp are both reachable and the first key press lands on a reading instead of skipping one.
  const [at, setAt] = useState<number | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const open = useContext(EvidenceCtx);
  const svg = useRef<SVGSVGElement | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    setAt(null);
    setStep(null);
    api
      .sensorStreams(caseId)
      .then((r) => live && setData(r))
      .catch((e: unknown) => live && setErr(message(e)));
    return () => {
      live = false;
    };
  }, [caseId, stateKey]);

  const geo = useMemo(() => {
    if (!data?.applicable) return null;
    const stored = data.series.find((s) => s.key === "stored")?.points ?? [];
    const ref = data.series.find((s) => s.key === "reference")?.points ?? [];
    const all = [...stored, ...ref];
    if (!all.length) return null;
    const [lo, hi] = data.permitted_range_c ?? [0, 0];
    const t0 = Math.min(...all.map((p) => ms(p.ts)));
    const t1 = Math.max(...all.map((p) => ms(p.ts)));
    const y0 = Math.floor(Math.min(lo, ...all.map((p) => p.temp_c)) - 0.5);
    const y1 = Math.ceil(Math.max(hi, ...all.map((p) => p.temp_c)) + 0.5);
    const x = (t: number) =>
      PLOT_L + ((t - t0) / Math.max(1, t1 - t0)) * (PLOT_R - PLOT_L);
    const y = (v: number) =>
      H - M.b - ((v - y0) / Math.max(1, y1 - y0)) * (H - M.t - M.b);
    const path = (pts: SensorPoint[]) =>
      pts
        .map(
          (p, i) =>
            `${i ? "L" : "M"}${x(ms(p.ts)).toFixed(1)} ${y(p.temp_c).toFixed(1)}`,
        )
        .join(" ");
    const range = y1 - y0;
    const yStep = range > 60 ? 20 : range > 30 ? 10 : range > 12 ? 4 : 2;
    const yTicks: number[] = [];
    for (let v = Math.ceil(y0 / yStep) * yStep; v <= y1; v += yStep) yTicks.push(v);
    // at most eight time labels, however long the capture is
    const span = Math.max(1, t1 - t0);
    const every = TICK_STEPS.find((s) => span / s <= 8) ?? Math.ceil(span / 8 / HOUR) * HOUR;
    const xTicks: number[] = [];
    for (let t = Math.ceil(t0 / every) * every; t <= t1; t += every) xTicks.push(t);
    return { stored, ref, t0, t1, lo, hi, x, y, path, yTicks, xTicks, days: span > 24 * HOUR };
  }, [data]);

  if (err)
    return (
      <div className="banner err small" role="alert">
        The temperature records could not be loaded: {err}
      </div>
    );
  if (!data || !data.applicable) return null;

  const all = data.discrepancies ?? [];
  const unexplained = all.filter((d) => d.classification === "unexplained");
  const isolated = all.filter((d) => d.classification === "isolated_reading");
  const notAssessable = data.status === "not_assessable";
  const refSeries = data.series.find((s) => s.key === "reference");
  const storedSeries = data.series.find((s) => s.key === "stored");
  const cut = data.series.filter((s) => s.truncated);
  const limits = (data.coverage_limits ?? []).filter((l) => l !== data.status_reason);

  // what is stepped through with the arrow keys: the reference readings, or the stored ones if there are none
  const base = geo ? (geo.ref.length ? geo.ref : geo.stored) : [];
  const baseIsRef = !!geo && geo.ref.length > 0;
  const firstStep = () => {
    if (!unexplained[0]) return 0;
    const i = base.findIndex((p) => ms(p.ts) >= ms(unexplained[0].start));
    return i < 0 ? 0 : i;
  };
  const move = (clientX: number) => {
    if (!geo || !svg.current) return;
    const box = svg.current.getBoundingClientRect();
    const vx = ((clientX - box.left) / Math.max(1, box.width)) * W;
    const f = Math.min(1, Math.max(0, (vx - PLOT_L) / (PLOT_R - PLOT_L)));
    setStep(null);
    setAt(geo.t0 + f * (geo.t1 - geo.t0));
  };
  const key = (dir: 1 | -1) => {
    if (!base.length) return;
    const next = step == null ? firstStep() : Math.min(base.length - 1, Math.max(0, step + dir));
    setStep(next);
    setAt(ms(base[next].ts));
  };
  const pinned = step != null ? (base[step] ?? null) : null;
  const hoverRef =
    geo && at != null ? (baseIsRef && pinned ? pinned : nearest(geo.ref, at)) : null;
  const hoverStored =
    geo && at != null ? (!baseIsRef && pinned ? pinned : nearest(geo.stored, at)) : null;
  const hx = geo && at != null ? geo.x(at) : null;
  const stamp = (t: number) => {
    const iso = new Date(t).toISOString();
    return geo?.days ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}` : iso.slice(11, 16);
  };

  const headline = notAssessable
    ? (data.status_reason ?? "The two records could not be compared in this evidence view.")
    : (TEMP_HEADLINE[data.status] ?? words(data.status)) +
      (isolated.length && !unexplained.length
        ? ` ${isolated.length} single reading${isolated.length === 1 ? "" : "s"} differed; see the table.`
        : "");

  return (
    <section className="panel temp-records" data-testid="temperature-records">
      <div className="column-title">
        <h2>Two temperature records</h2>
        <span>{data.sensor} · UTC</span>
      </div>
      <p
        className={
          "headline " +
          (notAssessable ? "amber" : unexplained.length ? "bad" : "")
        }
        data-testid="temperature-status"
      >
        {headline}
      </p>
      <ul className="temp-legend" aria-label="Series">
        {[refSeries, storedSeries].map(
          (s) =>
            s && (
              <li key={s.key}>
                <i className={`key ${s.key === "reference" ? "ref" : "stored"}`} aria-hidden />
                {s.label}
                <small>
                  {!s.present
                    ? "not in this bundle"
                    : (EXPOSURE[s.tamper_exposure ?? ""] ?? "")}
                </small>
              </li>
            ),
        )}
      </ul>
      {geo && (
        <div className="temp-plot">
          <svg
            ref={svg}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            tabIndex={0}
            aria-label={`Temperature over time for ${data.sensor}: the reference logger and the readings stored on the hub. Use the arrow keys to read values.`}
            onPointerMove={(e) => move(e.clientX)}
            onPointerLeave={() => {
              if (step == null) setAt(null);
            }}
            onBlur={() => {
              setStep(null);
              setAt(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") key(1);
              else if (e.key === "ArrowLeft") key(-1);
              else return;
              e.preventDefault();
            }}
          >
            <rect
              className="band"
              x={PLOT_L}
              width={PLOT_R - PLOT_L}
              y={geo.y(geo.hi)}
              height={Math.max(0, geo.y(geo.lo) - geo.y(geo.hi))}
            />
            {geo.yTicks.map((v) => (
              <g key={v}>
                <line className="grid" x1={PLOT_L} x2={PLOT_R} y1={geo.y(v)} y2={geo.y(v)} />
                <text className="tick" x={PLOT_L - 6} y={geo.y(v) + 3} textAnchor="end">
                  {v}
                </text>
              </g>
            ))}
            <text className="tick" x={PLOT_L - 6} y={M.t - 12} textAnchor="end">
              °C
            </text>
            <text className="region-label" x={PLOT_L + 5} y={geo.y(geo.hi) + 11}>
              Permitted {geo.lo}–{geo.hi} °C
            </text>
            {(data.maintenance_windows ?? []).map((w, i) => {
              if (!w.start || !w.end) return null;
              const a = geo.x(ms(w.start));
              const b = geo.x(ms(w.end));
              if (b < PLOT_L || a > PLOT_R) return null; // entirely outside what was recorded
              const x0 = clampX(a);
              const x1 = Math.max(x0 + 2, clampX(b));
              const right = x0 + 150 > PLOT_R;
              return (
                <g key={i}>
                  <rect className="maintenance" x={x0} width={x1 - x0} y={M.t} height={H - M.t - M.b} />
                  <text
                    className="region-label"
                    x={right ? x1 - 3 : x0 + 3}
                    y={H - M.b - 5 - (i % 2) * 12}
                    textAnchor={right ? "end" : "start"}
                  >
                    Maintenance {w.id}
                  </text>
                </g>
              );
            })}
            {unexplained.map((d, i) => {
              const a = geo.x(ms(d.start));
              const b = geo.x(ms(d.end));
              if (b < PLOT_L || a > PLOT_R) return null;
              const x0 = clampX(a);
              const x1 = Math.max(x0 + 3, clampX(b));
              // the label goes inside a wide interval, otherwise beside it on whichever side has room;
              // rows alternate so neighbouring intervals do not print over each other
              const inside = x1 - x0 >= 120;
              const rightRoom = x1 + 112 <= PLOT_R;
              const lx = inside ? x0 + 4 : rightRoom ? x1 + 4 : Math.max(PLOT_L + 108, x0 - 4);
              const anchor = inside || rightRoom ? "start" : "end";
              return (
                <g key={d.discrepancy_id} data-testid="temperature-disagreement">
                  <rect className="disagree" x={x0} width={x1 - x0} y={M.t} height={H - M.t - M.b} />
                  <line className="disagree-edge" x1={x0} x2={x0} y1={M.t} y2={H - M.b} />
                  <line className="disagree-edge" x1={x1} x2={x1} y1={M.t} y2={H - M.b} />
                  <text
                    className="region-label strong"
                    x={lx}
                    y={M.t + 11 + (i % 3) * 12}
                    textAnchor={anchor}
                  >
                    ⚠ Records disagree
                  </text>
                </g>
              );
            })}
            <line className="axis" x1={PLOT_L} x2={PLOT_R} y1={H - M.b} y2={H - M.b} />
            {geo.xTicks.map((t) => (
              <text key={t} className="tick" x={geo.x(t)} y={H - M.b + 14} textAnchor="middle">
                {stamp(t)}
              </text>
            ))}
            {geo.stored.length > 1 && <path className="line stored" d={geo.path(geo.stored)} />}
            {geo.ref.length > 1 && <path className="line ref" d={geo.path(geo.ref)} />}
            {geo.stored.length === 1 && (
              <circle className="dot stored" cx={geo.x(ms(geo.stored[0].ts))} cy={geo.y(geo.stored[0].temp_c)} r={4} />
            )}
            {geo.ref.length === 1 && (
              <circle className="dot ref" cx={geo.x(ms(geo.ref[0].ts))} cy={geo.y(geo.ref[0].temp_c)} r={4} />
            )}
            {isolated.map((d) => (
              <circle
                key={d.discrepancy_id}
                className="isolated"
                data-testid="temperature-isolated"
                cx={clampX(geo.x(ms(d.start)))}
                cy={geo.y(d.reference_range_c[0])}
                r={6}
              />
            ))}
            {hx != null && (
              <g aria-hidden>
                <line className="crosshair" x1={hx} x2={hx} y1={M.t} y2={H - M.b} />
                {hoverStored && (
                  <circle
                    className="dot stored"
                    cx={geo.x(ms(hoverStored.ts))}
                    cy={geo.y(hoverStored.temp_c)}
                    r={4}
                  />
                )}
                {hoverRef && (
                  <circle
                    className="dot ref"
                    cx={geo.x(ms(hoverRef.ts))}
                    cy={geo.y(hoverRef.temp_c)}
                    r={4}
                  />
                )}
              </g>
            )}
          </svg>
          {hx != null && at != null && (
            <div
              className={"temp-tip" + (hx > W * 0.55 ? " left" : "")}
              style={{ left: `${(hx / W) * 100}%` }}
              role="status"
              data-testid="temperature-tip"
            >
              <span className="when">{stamp(at)} UTC</span>
              {hoverRef && (
                <span data-testid="tip-reference">
                  <i className="key ref" aria-hidden />
                  <b>{hoverRef.temp_c.toFixed(1)} °C</b> reference, {hhmmss(hoverRef.ts)}
                </span>
              )}
              {hoverStored && (
                <span data-testid="tip-stored">
                  <i className="key stored" aria-hidden />
                  <b>{hoverStored.temp_c.toFixed(1)} °C</b> stored, {hhmmss(hoverStored.ts)}
                </span>
              )}
            </div>
          )}
        </div>
      )}
      {cut.map((s) => (
        <p key={s.key} className="small amber" data-testid="temperature-truncated">
          {s.label}: the first {s.points.length.toLocaleString()} of{" "}
          {s.total_points.toLocaleString()} readings are drawn.
        </p>
      ))}
      {limits.map((l, i) => (
        <p key={i} className="small amber" data-testid="temperature-limit">
          {l}
        </p>
      ))}
      {notAssessable ? (
        <p className="small muted" data-testid="temperature-not-compared">
          Not compared in this evidence view, so no differences and no excursions
          are counted. That is unknown, not none.
        </p>
      ) : (
        <details className="temp-table" open={unexplained.length > 0 || isolated.length > 0}>
          <summary>
            Where the records differ ({all.length}) and where the reference left
            the permitted range ({(data.excursions ?? []).length})
          </summary>
          {all.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Interval, UTC</th>
                  <th>Reference</th>
                  <th>Stored</th>
                  <th>Reading</th>
                  <th>Records</th>
                </tr>
              </thead>
              <tbody>
                {all.map((d) => (
                  <tr key={d.discrepancy_id} data-classification={d.classification}>
                    <td>
                      {hhmmss(d.start)}
                      {d.end !== d.start && `–${hhmmss(d.end)}`}
                    </td>
                    <td>
                      {d.reference_range_c[0]} to {d.reference_range_c[1]} °C
                    </td>
                    <td>
                      {d.local_range_c[0]} to {d.local_range_c[1]} °C
                    </td>
                    <td>
                      {DISCREPANCY[d.classification] ?? words(d.classification)}
                      {d.maintenance_id ? ` (${d.maintenance_id})` : ""}
                    </td>
                    <td>
                      <Chips
                        ids={[
                          ...d.reference_event_ids.slice(0, 2),
                          ...d.local_event_ids.slice(0, 2),
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {(data.excursions ?? []).map((e) => (
            <p key={e.excursion_id} className="small">
              The reference logger left the permitted range from {hhmmss(e.start)}{" "}
              to {hhmmss(e.end)} UTC, peaking at {e.peak_c} °C.{" "}
              {e.local_agrees
                ? "The stored record shows the same warming."
                : "The stored record does not show it."}{" "}
              <button className="linkish" onClick={() => open(e.reference_event_ids[0])}>
                Open the first reference reading
              </button>
            </p>
          ))}
        </details>
      )}
      <p className="small muted">
        {(data.limits ?? [])[0]
          ? `Limit: ${(data.limits ?? [])[0]}.`
          : "A temperature record describes the refrigerator, not who handled the record."}{" "}
        {data.produced_by}
      </p>
    </section>
  );
}

// --------------------------------------------------------------------------- second-run evaluation

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
        <small className="mono">{s.suites.map((x) => x.suite).join(" + ")}</small>
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

const FIXTURE_WORDS: Record<string, string> = {
  none: "No incident · an ordinary day",
  "inside-job-plain": "Inside job · scripted scenario",
  "inside-job-coverup": "Inside job with a removed log line · scripted scenario",
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
  const run = async (what: string, key: string, fn: (clientToken: string) => Promise<void>) => {
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
                This choice is yours, never the model's. The case looks the
                same either way until its answer is unsealed.
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

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
  onToggle,
}: {
  a: QuestionAnswer;
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  const limits = a.limitations ?? [];
  const plain = a.status === "unavailable" || a.status === "failed";
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
        <span className="tag">{ANSWER_STATUS[a.status] ?? words(a.status)}</span>
      </summary>
      {a.status === "pending" && (
        <p role="status" className="small muted">
          Answering from this case's evidence. At most three model calls.
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
  const alive = useRef(0);

  const put = useCallback((a: QuestionAnswer) => {
    setItems((cur) =>
      cur.some((x) => x.question_id === a.question_id)
        ? cur.map((x) => (x.question_id === a.question_id ? a : x))
        : [...cur, a],
    );
  }, []);

  const follow = useCallback(
    async (a: QuestionAnswer, gen: number) => {
      let cur = a;
      for (let i = 0; i < 80 && cur.status === "pending"; i++) {
        await new Promise((r) => window.setTimeout(r, 1500));
        if (gen !== alive.current) return;
        cur = await api.question(caseId, cur.question_id);
        if (gen !== alive.current) return;
        put(cur);
      }
    },
    [caseId, put],
  );

  useEffect(() => {
    const gen = ++alive.current;
    setItems([]);
    setErr(null);
    setText("");
    setBusy(false);
    setOpenId(null);
    if (!available) return;
    api
      .questions(caseId)
      .then((r) => {
        if (gen !== alive.current) return;
        setItems(r.questions);
        const pending = r.questions.find((x) => x.status === "pending");
        if (pending) {
          setBusy(true);
          follow(pending, gen)
            .catch(() => undefined)
            .finally(() => gen === alive.current && setBusy(false));
        }
      })
      .catch((e: unknown) => gen === alive.current && setErr(message(e)));
    return () => {
      alive.current += 1;
    };
  }, [caseId, available, follow]);

  const submit = async () => {
    const question = text.trim();
    if (!question || busy || !available) return;
    const gen = alive.current;
    setBusy(true);
    setErr(null);
    try {
      const a = await api.ask(caseId, question, token());
      if (gen !== alive.current) return;
      put(a);
      setOpenId(a.question_id);
      setText("");
      await follow(a, gen);
    } catch (e) {
      if (gen !== alive.current) return;
      setErr(
        e instanceof ApiError && e.status === 409
          ? "Another question is still being answered for this case."
          : message(e),
      );
    } finally {
      if (gen === alive.current) setBusy(false);
    }
  };

  const caps = runtime?.capabilities?.questions;
  const max = caps?.max_question_chars ?? 1000;
  const reason = !available
    ? "Questions become available after the report is drafted."
    : busy
      ? "Answering from this case's evidence…"
      : caps?.model_answers === "CONFIGURED"
        ? "A model answers from this case's evidence only. Each claim is checked against the records it cites. A question never changes the report."
        : "No model is configured on this server, so a question is recorded and returned unanswered. The cited explanations need no model.";
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

  if (parent)
    return (
      <section className="source-experiment" data-testid="source-experiment">
        <h4>Evidence view without the {withheldWords(view.case.excluded_sources)}</h4>
        <p className="small muted">
          Derived from another case with {(view.case.excluded_sources ?? []).length}{" "}
          file{(view.case.excluded_sources ?? []).length === 1 ? "" : "s"} withheld.
          The original evidence and its report are unchanged.
        </p>
        <button data-testid="btn-open-original" onClick={() => onOpenCase(parent)}>
          Open the original case
        </button>
      </section>
    );

  const ready = hasReport(view.case.state) && !!view.report && !!chosen;
  const derive = async () => {
    if (!chosen || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const made = await api.createSourceExperiment(id, chosen[1].ids, token());
      onOpenCase(made.child_case_id);
    } catch (e) {
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
  if (!exp || !cmp) return null;
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
const ms = (s: string) => Date.parse(s);

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

const TEMP_HEADLINE: Record<string, string> = {
  discrepancy_unexplained:
    "The two records disagree, and no stated maintenance explains it.",
  discrepancy_explained:
    "The two records disagree only inside a stated maintenance window.",
  consistent: "The two records agree within the stated tolerance.",
};
const DISCREPANCY: Record<string, string> = {
  unexplained: "Unexplained",
  explained_maintenance: "Inside a maintenance window",
  isolated_reading: "A single reading",
};

export function TemperatureRecords({
  caseId,
  stateKey,
}: {
  caseId: string;
  stateKey: string;
}) {
  const [data, setData] = useState<SensorStreams | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [at, setAt] = useState<number | null>(null);
  const open = useContext(EvidenceCtx);
  const svg = useRef<SVGSVGElement | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    setAt(null);
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
      M.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - M.l - M.r);
    const y = (v: number) =>
      H - M.b - ((v - y0) / Math.max(1, y1 - y0)) * (H - M.t - M.b);
    const path = (pts: SensorPoint[]) =>
      pts
        .map(
          (p, i) =>
            `${i ? "L" : "M"}${x(ms(p.ts)).toFixed(1)} ${y(p.temp_c).toFixed(1)}`,
        )
        .join(" ");
    const step = y1 - y0 > 12 ? 4 : 2;
    const yTicks: number[] = [];
    for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) yTicks.push(v);
    const hour = 3600_000;
    const span = t1 - t0;
    const every = span > 8 * hour ? 2 * hour : span > 3 * hour ? hour : hour / 2;
    const xTicks: number[] = [];
    for (let t = Math.ceil(t0 / every) * every; t <= t1; t += every) xTicks.push(t);
    return { stored, ref, t0, t1, lo, hi, x, y, path, yTicks, xTicks };
  }, [data]);

  if (err)
    return (
      <div className="banner err small" role="alert">
        The temperature records could not be loaded: {err}
      </div>
    );
  if (!data || !data.applicable) return null;

  const unexplained = (data.discrepancies ?? []).filter(
    (d) => d.classification === "unexplained",
  );
  const notAssessable = data.status === "not_assessable";
  const refSeries = data.series.find((s) => s.key === "reference");
  const storedSeries = data.series.find((s) => s.key === "stored");
  const move = (clientX: number) => {
    if (!geo || !svg.current) return;
    const box = svg.current.getBoundingClientRect();
    const vx = ((clientX - box.left) / Math.max(1, box.width)) * W;
    const f = Math.min(1, Math.max(0, (vx - M.l) / (W - M.l - M.r)));
    setAt(geo.t0 + f * (geo.t1 - geo.t0));
  };
  const stepKey = (dir: 1 | -1) => {
    if (!geo) return;
    const base = geo.ref.length ? geo.ref : geo.stored;
    const cur = at ?? (unexplained[0] ? ms(unexplained[0].start) : geo.t0);
    const i = base.findIndex((p) => ms(p.ts) >= cur);
    const j = Math.min(base.length - 1, Math.max(0, (i < 0 ? base.length - 1 : i) + dir));
    setAt(ms(base[j].ts));
  };
  const hoverStored = geo && at != null ? nearest(geo.stored, at) : null;
  const hoverRef = geo && at != null ? nearest(geo.ref, at) : null;
  const hx = geo && at != null ? geo.x(at) : null;
  const utc = (t: number) => new Date(t).toISOString().slice(11, 16);

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
        {notAssessable
          ? data.status_reason
          : (TEMP_HEADLINE[data.status] ?? words(data.status))}
      </p>
      <ul className="temp-legend" aria-label="Series">
        {refSeries && (
          <li>
            <i className="key ref" aria-hidden />
            {refSeries.label}
            <small>
              {refSeries.present
                ? "independent · cannot be written from the hub"
                : "not in this bundle"}
            </small>
          </li>
        )}
        {storedSeries && (
          <li>
            <i className="key stored" aria-hidden />
            {storedSeries.label}
            <small>
              {storedSeries.present ? "writable on the hub" : "not in this bundle"}
            </small>
          </li>
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
            onPointerLeave={() => setAt(null)}
            onBlur={() => setAt(null)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") stepKey(1);
              else if (e.key === "ArrowLeft") stepKey(-1);
              else return;
              e.preventDefault();
            }}
          >
            <rect
              className="band"
              x={M.l}
              width={W - M.l - M.r}
              y={geo.y(geo.hi)}
              height={Math.max(0, geo.y(geo.lo) - geo.y(geo.hi))}
            />
            {geo.yTicks.map((v) => (
              <g key={v}>
                <line className="grid" x1={M.l} x2={W - M.r} y1={geo.y(v)} y2={geo.y(v)} />
                <text className="tick" x={M.l - 6} y={geo.y(v) + 3} textAnchor="end">
                  {v}
                </text>
              </g>
            ))}
            <text className="tick" x={M.l - 6} y={M.t - 12} textAnchor="end">
              °C
            </text>
            <text className="region-label" x={M.l + 5} y={geo.y(geo.hi) + 11}>
              Permitted {geo.lo}–{geo.hi} °C
            </text>
            {(data.maintenance_windows ?? []).map((w, i) =>
              w.start && w.end ? (
                <g key={i}>
                  <rect
                    className="maintenance"
                    x={geo.x(ms(w.start))}
                    width={Math.max(2, geo.x(ms(w.end)) - geo.x(ms(w.start)))}
                    y={M.t}
                    height={H - M.t - M.b}
                  />
                  <text
                    className="region-label"
                    x={geo.x(ms(w.start)) + 3}
                    y={H - M.b - 5}
                  >
                    Maintenance {w.id}
                  </text>
                </g>
              ) : null,
            )}
            {unexplained.map((d) => {
              const x0 = geo.x(ms(d.start));
              const x1 = Math.max(x0 + 3, geo.x(ms(d.end)));
              return (
                <g key={d.discrepancy_id} data-testid="temperature-disagreement">
                  <rect className="disagree" x={x0} width={x1 - x0} y={M.t} height={H - M.t - M.b} />
                  <line className="disagree-edge" x1={x0} x2={x0} y1={M.t} y2={H - M.b} />
                  <line className="disagree-edge" x1={x1} x2={x1} y1={M.t} y2={H - M.b} />
                  <text
                    className="region-label strong"
                    x={Math.min(W - M.r - 4, x1 + 4) - (x1 + 110 > W - M.r ? x1 - x0 + 8 : 0)}
                    y={M.t + 11}
                    textAnchor={x1 + 110 > W - M.r ? "end" : "start"}
                  >
                    ⚠ Records disagree
                  </text>
                </g>
              );
            })}
            <line className="axis" x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
            {geo.xTicks.map((t) => (
              <text key={t} className="tick" x={geo.x(t)} y={H - M.b + 14} textAnchor="middle">
                {utc(t)}
              </text>
            ))}
            {geo.stored.length > 0 && <path className="line stored" d={geo.path(geo.stored)} />}
            {geo.ref.length > 0 && <path className="line ref" d={geo.path(geo.ref)} />}
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
              className={"temp-tip" + (hx > W * 0.62 ? " left" : "")}
              style={{ left: `${(hx / W) * 100}%` }}
              role="status"
              data-testid="temperature-tip"
            >
              <span className="when">{utc(at)} UTC</span>
              {hoverRef && (
                <span>
                  <i className="key ref" aria-hidden />
                  <b>{hoverRef.temp_c.toFixed(1)} °C</b> reference, {hhmmss(hoverRef.ts)}
                </span>
              )}
              {hoverStored && (
                <span>
                  <i className="key stored" aria-hidden />
                  <b>{hoverStored.temp_c.toFixed(1)} °C</b> stored, {hhmmss(hoverStored.ts)}
                </span>
              )}
            </div>
          )}
        </div>
      )}
      <details className="temp-table" open={unexplained.length > 0}>
        <summary>
          Where the records differ ({(data.discrepancies ?? []).length}) and
          where the reference left the permitted range (
          {(data.excursions ?? []).length})
        </summary>
        {(data.discrepancies ?? []).length > 0 && (
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
              {(data.discrepancies ?? []).map((d) => (
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
        {(data.coverage_limits ?? []).map((l, i) => (
          <p key={i} className="small amber">
            {l}
          </p>
        ))}
      </details>
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
  const live = runtime?.capabilities?.scenario_designer?.model === "CONFIGURED";
  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    setErr(null);
    try {
      await fn();
    } catch (e) {
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
        {live
          ? "One bounded model response, then the case is generated offline."
          : "No model is configured on this server, so a default environment is returned and labeled as a default."}
      </p>
      <button
        className="primary"
        data-testid="btn-design-ask"
        disabled={busy !== null}
        onClick={() =>
          run("ask", async () => {
            setDesign(await api.design(token()));
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
                  run("generate", async () => {
                    onCase(
                      await api.createFromDesign(design.design_id, fixture, mode),
                    );
                  })
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

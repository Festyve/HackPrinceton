import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  CaseView,
  ExcludedSource,
  ExperimentClaim,
  SourceExperiment,
} from "../api";
import { Chips } from "../common";
import { CLAIM_TITLES, hasReport } from "../model";
import { words, message, useActionToken } from "./operation";

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
    const gone =
      exp?.role === "derived" && exp.comparison == null && !!exp.note;
    return (
      <section className="source-experiment" data-testid="source-experiment">
        <h4>
          Evidence view without the {withheldWords(view.case.excluded_sources)}
        </h4>
        <p className="small muted">
          Derived from another case with {n} file{n === 1 ? "" : "s"} withheld.{" "}
          {/* until the server has answered, say neither: the original may have been reset */}
          {exp == null
            ? ""
            : gone
              ? exp.note
              : "Deriving this view did not change the original evidence or its report."}
        </p>
        {!gone && (
          <button
            data-testid="btn-open-original"
            onClick={() => onOpenCase(parent)}
          >
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
      <button
        data-testid="btn-derive"
        disabled={!ready || busy}
        onClick={derive}
      >
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
              <button
                className="linkish"
                onClick={() => onOpenCase(c.child_case_id)}
              >
                Without the {withheldWords(c.excluded_sources)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const CHANGE: Record<ExperimentClaim["change"], { word: string; cls: string }> =
  {
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

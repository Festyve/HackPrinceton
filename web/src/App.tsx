import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { CaseView, Presets, RawView, Runtime, ServerEvent } from "./api";
import { applyEvents, emptyRun, hasReport } from "./model";
import type { Run } from "./model";
import { EvidenceCtx } from "./common";
import { LeftColumn, CenterColumn } from "./panels";
import { EvidenceColumn } from "./evidence";
import { ScoreOverlay } from "./score";
import { BenchmarkTab } from "./bench";

const EVENT_TYPES = ["state", "stage", "todo", "agent", "tool", "finding", "note", "attribution", "usage", "report", "review", "locked", "reveal", "error", "gone"];
const REFETCH = new Set(["state", "report", "review", "locked", "reveal"]);
const TERMINAL = new Set(["scored", "failed", "cancelled"]);

const hashId = (): string | null => {
  const m = /case=([^&]+)/.exec(window.location.hash);
  return m ? decodeURIComponent(m[1]) : null;
};
const setHash = (id: string | null) => {
  const url = window.location.pathname + window.location.search + (id ? "#case=" + encodeURIComponent(id) : "");
  window.history.replaceState(null, "", url);
};

export interface RawTarget { artifact: string; line: number; eventId?: string }

export default function App() {
  const [tab, setTab] = useState<"case" | "benchmark">("case");
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [presets, setPresets] = useState<Presets | null>(null);
  const [presetErr, setPresetErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ kind: "preset" | "replay"; id: string } | null>(null);
  const [view, setView] = useState<CaseView | null>(null);
  const [run, setRun] = useState<Run>(emptyRun());
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reviewMsg, setReviewMsg] = useState<string | null>(null);
  const [raw, setRaw] = useState<{ loading: boolean; error: string | null; data: RawView | null; eventId?: string } | null>(null);
  const [showScore, setShowScore] = useState(true);

  const esRef = useRef<EventSource | null>(null);
  const genRef = useRef(0);
  const caseIdRef = useRef<string | null>(null);
  const lastSeqRef = useRef(0);
  const retryRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    api.runtime().then(setRuntime).catch(() => setRuntime(null));
    api.presets().then(setPresets).catch((e: unknown) => setPresetErr(String(e instanceof Error ? e.message : e)));
  }, []);

  const closeStream = useCallback(() => {
    genRef.current += 1;
    window.clearTimeout(retryRef.current);
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
  }, []);

  const clearCase = useCallback(() => {
    closeStream();
    caseIdRef.current = null;
    lastSeqRef.current = 0;
    setView(null); setRun(emptyRun()); setRaw(null); setReviewMsg(null); setShowScore(true);
    setHash(null);
  }, [closeStream]);

  const refetch = useCallback(async (id: string, gen: number) => {
    try {
      const v = await api.getCase(id);
      if (gen === genRef.current) setView(v);
      return v;
    } catch (e) {
      if (gen === genRef.current && e instanceof ApiError && e.status === 404) { clearCase(); setErr("That case no longer exists."); }
      return null;
    }
  }, [clearCase]);

  const feed = useCallback((evs: ServerEvent[]) => {
    if (!evs.length) return;
    setRun((r) => { const n = applyEvents(r, evs); lastSeqRef.current = n.lastSeq; return n; });
  }, []);

  const openStream = useCallback((id: string, gen: number) => {
    const es = new EventSource(`/api/cases/${encodeURIComponent(id)}/events?after=${lastSeqRef.current}`);
    esRef.current = es;
    const onMsg = (m: MessageEvent<string>) => {
      if (gen !== genRef.current) return;
      try {
        const ev = JSON.parse(m.data) as ServerEvent;
        feed([ev]);
        if (ev.type === "gone") { es.close(); clearCase(); setErr("The case was deleted."); return; }
        if (REFETCH.has(ev.type)) void refetch(id, gen);
      } catch { /* ignore malformed */ }
    };
    for (const t of EVENT_TYPES) es.addEventListener(t, onMsg as EventListener);
    es.onerror = () => {
      if (gen !== genRef.current) return;
      es.close();
      if (esRef.current === es) esRef.current = null;
      retryRef.current = window.setTimeout(async () => {
        if (gen !== genRef.current) return;
        try {
          const j = await api.eventsJson(id, lastSeqRef.current);
          if (gen !== genRef.current) return;
          feed(j.events);
          const v = await refetch(id, gen);
          if (v && TERMINAL.has(v.case.state)) return;
          openStream(id, gen);
        } catch (e) {
          if (e instanceof ApiError && e.status === 404) { clearCase(); setErr("That case no longer exists."); return; }
          openStream(id, gen);
        }
      }, 1000);
    };
  }, [feed, refetch, clearCase]);

  const attach = useCallback(async (id: string, initial?: CaseView) => {
    closeStream();
    const gen = genRef.current;
    caseIdRef.current = id;
    lastSeqRef.current = 0;
    setRun(emptyRun()); setRaw(null); setReviewMsg(null); setShowScore(true);
    setHash(id);
    try {
      const v = initial ?? (await api.getCase(id));
      if (gen !== genRef.current) return;
      setView(v);
      const j = await api.eventsJson(id, 0);
      if (gen !== genRef.current) return;
      feed(j.events);
      const v2 = await api.getCase(id);
      if (gen !== genRef.current) return;
      setView(v2);
      if (!TERMINAL.has(v2.case.state)) openStream(id, gen);
    } catch (e) {
      if (gen !== genRef.current) return;
      if (e instanceof ApiError && e.status === 404) { clearCase(); setErr("That case no longer exists (it was reset or the server restarted)."); }
      else setErr(e instanceof Error ? e.message : String(e));
    }
  }, [closeStream, feed, openStream, clearCase]);

  useEffect(() => {
    const id = hashId();
    if (id) void attach(id);
    return closeStream;
  }, [attach, closeStream]);

  const guard = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setErr(null);
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(null); }
  };

  const doRun = () => guard("run", async () => {
    if (!selected) return;
    const v = selected.kind === "preset" ? await api.createCase(selected.id) : await api.openReplay(selected.id);
    await attach(v.case.case_id, v);
  });
  const doReset = () => guard("reset", async () => {
    const id = caseIdRef.current;
    if (id) { try { await api.reset(id); } catch (e) { if (!(e instanceof ApiError && e.status === 404)) throw e; } }
    clearCase();
  });
  const doReview = (d: "accept" | "reject") => guard("review", async () => {
    const id = caseIdRef.current; if (!id) return;
    const v = await api.review(id, d);
    setView(v);
    setReviewMsg(null);
  });
  const doReveal = () => guard("reveal", async () => {
    const id = caseIdRef.current; if (!id) return;
    try {
      const v = await api.reveal(id);
      setView(v); setShowScore(true);
    } catch (e) {
      setReviewMsg(e instanceof Error ? e.message : String(e));
    }
  });

  const openEvidence = useCallback(async (target: string | RawTarget) => {
    const id = caseIdRef.current; if (!id) return;
    setRaw({ loading: true, error: null, data: null, eventId: typeof target === "string" ? target : target.eventId });
    try {
      let t: RawTarget;
      if (typeof target === "string") {
        const r = await api.evEvents(id, target);
        const e = r.events[0];
        if (!e || !e.artifact || e.line == null) throw new Error(r.missing.includes(target) ? `Event ${target} does not exist in this bundle.` : "No artifact reference for that event.");
        t = { artifact: e.artifact, line: e.line, eventId: target };
      } else t = target;
      const data = await api.raw(id, t.artifact, t.line);
      setRaw({ loading: false, error: null, data, eventId: t.eventId });
    } catch (e) {
      setRaw({ loading: false, error: e instanceof Error ? e.message : String(e), data: null });
    }
  }, []);

  const c = view?.case;
  const state = c?.state ?? "";
  const failed = state === "failed" || state === "cancelled";
  const bannerMsg = failed ? (c?.error || c?.detail || state) : run.error;
  const inFlight = !!view && !TERMINAL.has(state);

  return (
    <div className="app" data-testid="app-root">
      <header className="hdr">
        <div className="wordmark" aria-label="ALIBI">ALIBI</div>
        <nav className="tabs">
          <button data-testid="tab-case" className={tab === "case" ? "on" : ""} onClick={() => setTab("case")}>Case</button>
          <button data-testid="tab-benchmark" className={tab === "benchmark" ? "on" : ""} onClick={() => setTab("benchmark")}>Benchmark</button>
        </nav>
        <div className="badges">
          <span className="badge" data-testid="badge-evidence"><i>Evidence</i> {c?.labels.evidence_origin ?? "SIM"}</span>
          <span className="badge" data-testid="badge-inference"><i>Inference</i> {c ? c.labels.inference_label : "—"}</span>
          <span className="badge" data-testid="badge-playback"><i>Playback</i> {c?.labels.playback ?? "—"}</span>
          {c?.seed != null && <span className="badge"><i>Seed</i> {c.seed}</span>}
          <RuntimeChip rt={runtime} />
        </div>
        <span className="statepill" data-testid="case-state">{state}</span>
        <div className="hbtns">
          <button className="primary" data-testid="btn-run" onClick={doRun}
            disabled={busy !== null || !!view || !selected}
            title={view ? "Reset the current case first" : !selected ? "Select a preset first" : "Generate and investigate"}>
            {busy === "run" ? "Running…" : "Run"}
          </button>
          <button data-testid="btn-reset" onClick={doReset} disabled={busy !== null || !view}>{busy === "reset" ? "Resetting…" : "Reset"}</button>
        </div>
      </header>

      {err && !failed && <div className="banner err" role="alert" data-testid="error-banner">{err}</div>}
      {bannerMsg && (
        <div className="banner err" role="alert" data-testid="error-banner">
          <span>{"\u2716 "}{failed ? state.toUpperCase() + ": " : "Error: "}{bannerMsg}</span>
          {failed && <button onClick={doReset} disabled={busy !== null}>Reset</button>}
        </div>
      )}

      {tab === "benchmark" ? (
        <main className="single"><BenchmarkTab /></main>
      ) : !view ? (
        <main className="single">
          <StartState presets={presets} err={presetErr} selected={selected} onSelect={setSelected} />
        </main>
      ) : (
        <EvidenceCtx.Provider value={openEvidence}>
          <main className="grid">
            <LeftColumn view={view} run={run} />
            <CenterColumn view={view} run={run} busy={busy} reviewMsg={reviewMsg}
              onReview={doReview} onReveal={doReveal} inFlight={inFlight}
              onShowScore={() => setShowScore(true)} />
            {hasReport(state) ? (
              <EvidenceColumn caseId={view.case.case_id} view={view} run={run} raw={raw} />
            ) : (
              <section className="col"><h2>Evidence</h2><p className="muted">The host-versus-collector comparison appears once the report is drafted.</p></section>
            )}
          </main>
          {state === "scored" && view.reveal && showScore && (
            <ScoreOverlay view={view} run={run} onClose={() => setShowScore(false)} />
          )}
        </EvidenceCtx.Provider>
      )}
    </div>
  );
}

function RuntimeChip({ rt }: { rt: Runtime | null }) {
  const [open, setOpen] = useState(false);
  if (!rt) return <span className="badge" data-testid="runtime-status">Runtime: unknown</span>;
  const blocked = rt.live_inference === "BLOCKED";
  return (
    <span className="rt">
      <button className={"badge btnlike " + (blocked ? "blocked" : "ok")} data-testid="runtime-status"
        title={rt.live_block_reason ?? ""} onClick={() => setOpen(!open)} aria-expanded={open}>
        {blocked ? "\u26D4 Live AI: BLOCKED" : "Live AI: CONFIGURED"}
      </button>
      {open && <span className="pop">{rt.live_block_reason ?? "No reason given."}</span>}
    </span>
  );
}

function StartState(p: {
  presets: Presets | null; err: string | null;
  selected: { kind: "preset" | "replay"; id: string } | null;
  onSelect: (s: { kind: "preset" | "replay"; id: string }) => void;
}) {
  if (p.err) return <div className="banner err">Could not load presets: {p.err}</div>;
  if (!p.presets) return <p className="muted">Loading presets…</p>;
  return (
    <div className="start">
      <h1>Choose a case, then press Run</h1>
      <p className="muted">A bounded simulator stages a synthetic incident and seals what really happened. The investigator sees only frozen evidence.</p>
      <div className="cards">
        {p.presets.presets.map((x) => (
          <button key={x.id} data-testid={`preset-${x.id}`} className={"card" + (p.selected?.id === x.id && p.selected.kind === "preset" ? " sel" : "")}
            aria-pressed={p.selected?.id === x.id && p.selected.kind === "preset"} onClick={() => p.onSelect({ kind: "preset", id: x.id })}>
            <b>{x.title}</b>
            <span className="tag">difficulty {x.difficulty}</span>
            <span>{x.blurb}</span>
          </button>
        ))}
      </div>
      {p.presets.replays.length > 0 && (
        <>
          <h2>Recorded replays</h2>
          <div className="cards">
            {p.presets.replays.map((x) => (
              <button key={x.id} data-testid={`replay-${x.id}`} className={"card" + (p.selected?.id === x.id && p.selected.kind === "replay" ? " sel" : "")}
                aria-pressed={p.selected?.id === x.id && p.selected.kind === "replay"} onClick={() => p.onSelect({ kind: "replay", id: x.id })}>
                <b>{x.title}</b>
                <span className="tag">REPLAY</span>
                <span className="tag">{x.inference_label ?? x.inference_mode}</span>
                {x.model_id && <span className="mono">{x.model_id}</span>}
                {x.recorded_at && <span className="muted">recorded {x.recorded_at}</span>}
                {x.note && <span>{x.note}</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

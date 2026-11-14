import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { CaseView, Presets, RawView, Runtime, ServerEvent } from "./api";
import { applyEvents, emptyRun, hasReport } from "./model";
import type { Run } from "./model";
import { EvidenceCtx } from "./common";
import { CenterColumn, Ask } from "./panels";
import { Dialog } from "./dialog";
import {
  Sources,
  RuntimeDetails,
  ProgressActivity,
  humanState,
  originLabel,
} from "./workbench";
import { EvidenceColumn, RawViewer } from "./evidence";
import { ScoreOverlay } from "./score";
import { BenchmarkTab } from "./bench";
import {
  DesignerDialog,
  ExperimentComparison,
  QuestionPanel,
  TemperatureRecords,
} from "./phase2";

const EVENT_TYPES = [
  "state",
  "stage",
  "todo",
  "agent",
  "tool",
  "finding",
  "note",
  "attribution",
  "usage",
  "report",
  "review",
  "locked",
  "reveal",
  "error",
  "gone",
];
const REFETCH = new Set(["state", "report", "review", "locked", "reveal"]);
const TERMINAL = new Set(["scored", "failed", "cancelled"]);

const hashId = (): string | null => {
  const m = /case=([^&]+)/.exec(window.location.hash);
  return m ? decodeURIComponent(m[1]) : null;
};
const setHash = (id: string | null) => {
  const url =
    window.location.pathname +
    window.location.search +
    (id ? "#case=" + encodeURIComponent(id) : "");
  window.history.replaceState(null, "", url);
};

export interface RawTarget {
  artifact: string;
  line: number;
  eventId?: string;
}

export default function App() {
  const [tab, setTab] = useState<"case" | "benchmark">("case");
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [presets, setPresets] = useState<Presets | null>(null);
  const [presetErr, setPresetErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<{
    kind: "preset" | "replay";
    id: string;
  } | null>(null);
  const [view, setView] = useState<CaseView | null>(null);
  const [run, setRun] = useState<Run>(emptyRun());
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reviewMsg, setReviewMsg] = useState<string | null>(null);
  const [raw, setRaw] = useState<{
    loading: boolean;
    error: string | null;
    data: RawView | null;
    eventId?: string;
  } | null>(null);
  const [showScore, setShowScore] = useState(true);
  const [showDetails, setShowDetails] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [selectedHost, setSelectedHost] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const [mode, setMode] = useState<string | null>(null);
  const [showDesigner, setShowDesigner] = useState(false);
  const rawRequest = useRef(0);

  const esRef = useRef<EventSource | null>(null);
  const genRef = useRef(0);
  const caseIdRef = useRef<string | null>(null);
  const lastSeqRef = useRef(0);
  const retryRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    // What the server can do decides what the controls say, so a failed first request is tried again.
    let live = true;
    let tries = 0;
    const loadRuntime = () =>
      api
        .runtime()
        .then((r) => live && setRuntime(r))
        .catch(() => {
          if (!live) return;
          setRuntime(null);
          tries += 1;
          if (tries < 8) window.setTimeout(loadRuntime, Math.min(1500 * tries, 8000));
        });
    void loadRuntime();
    api
      .presets()
      .then(setPresets)
      .catch((e: unknown) =>
        setPresetErr(String(e instanceof Error ? e.message : e)),
      );
    return () => {
      live = false;
    };
  }, []);

  const closeStream = useCallback(() => {
    genRef.current += 1;
    window.clearTimeout(retryRef.current);
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const clearCase = useCallback(() => {
    closeStream();
    caseIdRef.current = null;
    lastSeqRef.current = 0;
    rawRequest.current += 1;
    setView(null);
    setAttaching(false);
    setRun(emptyRun());
    setRaw(null);
    setReviewMsg(null);
    setShowScore(true);
    setSelectedHost(null);
    setDisconnected(false);
    setShowLibrary(false);
    setHash(null);
  }, [closeStream]);

  const refetch = useCallback(
    async (id: string, gen: number) => {
      try {
        const v = await api.getCase(id);
        if (gen === genRef.current) setView(v);
        return v;
      } catch (e) {
        if (
          gen === genRef.current &&
          e instanceof ApiError &&
          e.status === 404
        ) {
          clearCase();
          setErr("That case no longer exists.");
        }
        return null;
      }
    },
    [clearCase],
  );

  const feed = useCallback((evs: ServerEvent[]) => {
    if (!evs.length) return;
    setRun((r) => {
      const n = applyEvents(r, evs);
      lastSeqRef.current = n.lastSeq;
      return n;
    });
  }, []);

  const openStream = useCallback(
    (id: string, gen: number) => {
      const es = new EventSource(
        `/api/cases/${encodeURIComponent(id)}/events?after=${lastSeqRef.current}`,
      );
      esRef.current = es;
      const onMsg = (m: MessageEvent<string>) => {
        if (gen !== genRef.current) return;
        try {
          const ev = JSON.parse(m.data) as ServerEvent;
          setDisconnected(false);
          feed([ev]);
          if (ev.type === "gone") {
            es.close();
            clearCase();
            setErr("The case was deleted.");
            return;
          }
          if (REFETCH.has(ev.type)) void refetch(id, gen);
        } catch {
          /* ignore malformed */
        }
      };
      for (const t of EVENT_TYPES)
        es.addEventListener(t, onMsg as EventListener);
      es.onerror = () => {
        if (gen !== genRef.current) return;
        es.close();
        setDisconnected(true);
        if (esRef.current === es) esRef.current = null;
        retryRef.current = window.setTimeout(async () => {
          if (gen !== genRef.current) return;
          try {
            const j = await api.eventsJson(id, lastSeqRef.current);
            if (gen !== genRef.current) return;
            setDisconnected(false);
            feed(j.events);
            const v = await refetch(id, gen);
            if (gen !== genRef.current) return;
            if (v && TERMINAL.has(v.case.state)) return;
            openStream(id, gen);
          } catch (e) {
            if (gen !== genRef.current) return;
            if (e instanceof ApiError && e.status === 404) {
              clearCase();
              setErr("That case no longer exists.");
              return;
            }
            openStream(id, gen);
          }
        }, 1000);
      };
    },
    [feed, refetch, clearCase],
  );

  const attach = useCallback(
    async (id: string, initial?: CaseView) => {
      closeStream();
      const gen = genRef.current;
      caseIdRef.current = id;
      setAttaching(true);
      setView(null);
      setShowDetails(false);
      lastSeqRef.current = 0;
      rawRequest.current += 1;
      setRun(emptyRun());
      setRaw(null);
      setReviewMsg(null);
      setShowScore(true);
      setShowLibrary(false);
      setSelectedHost(null);
      setDisconnected(false);
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
        if (e instanceof ApiError && e.status === 404) {
          clearCase();
          setErr(
            "That case no longer exists (it was reset or the server restarted).",
          );
        } else setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (gen === genRef.current) setAttaching(false);
      }
    },
    [closeStream, feed, openStream, clearCase],
  );

  useEffect(() => {
    const id = hashId();
    if (id) void attach(id);
    return closeStream;
  }, [attach, closeStream]);

  // A case link pasted into an already open tab changes only the hash: follow it.
  useEffect(() => {
    const onHash = () => {
      const id = hashId();
      if (id && id !== caseIdRef.current) void attach(id);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [attach]);

  const guard = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const doRun = (choice = selected) =>
    guard("run", async () => {
      if (!choice) return;
      setTab("case");
      const v =
        choice.kind === "preset"
          ? await api.createCase(choice.id, mode)
          : await api.openReplay(choice.id);
      await attach(v.case.case_id, v);
    });
  const doOpenCase = (id: string) => guard("run", () => attach(id));
  const doReset = () =>
    guard("reset", async () => {
      const id = caseIdRef.current;
      if (id) {
        try {
          await api.reset(id);
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
      }
      clearCase();
    });
  const doReview = (d: "accept" | "reject") =>
    guard("review", async () => {
      const id = caseIdRef.current;
      if (!id) return;
      const v = await api.review(id, d);
      setView(v);
      setReviewMsg(null);
    });
  const doReveal = () =>
    guard("reveal", async () => {
      const id = caseIdRef.current;
      if (!id) return;
      try {
        const v = await api.reveal(id);
        setView(v);
        setShowScore(true);
      } catch (e) {
        setReviewMsg(e instanceof Error ? e.message : String(e));
      }
    });

  const openEvidence = useCallback(async (target: string | RawTarget) => {
    const id = caseIdRef.current;
    if (!id) return;
    setShowDetails(false);
    const requestId = ++rawRequest.current;
    const gen = genRef.current;
    setRaw({
      loading: true,
      error: null,
      data: null,
      eventId: typeof target === "string" ? target : target.eventId,
    });
    try {
      let t: RawTarget;
      if (typeof target === "string") {
        const r = await api.evEvents(id, target);
        const e = r.events[0];
        if (!e || !e.artifact || e.line == null)
          throw new Error(
            r.missing.includes(target)
              ? `Event ${target} does not exist in this bundle.`
              : "No artifact reference for that event.",
          );
        t = { artifact: e.artifact, line: e.line, eventId: target };
      } else t = target;
      const data = await api.raw(id, t.artifact, t.line);
      if (requestId !== rawRequest.current || gen !== genRef.current) return;
      setRaw({ loading: false, error: null, data, eventId: t.eventId });
    } catch (e) {
      if (requestId !== rawRequest.current || gen !== genRef.current) return;
      setRaw({
        loading: false,
        error: e instanceof Error ? e.message : String(e),
        data: null,
      });
    }
  }, []);

  const c = view?.case;
  const state = c?.state ?? "";
  const failed = state === "failed" || state === "cancelled";
  const bannerMsg = failed ? c?.error || c?.detail || state : run.error;
  const title = view?.card?.title ?? c?.title ?? "Case library";
  const reviewPhase = state === "awaiting_review" || state === "report_locked";
  return (
    <EvidenceCtx.Provider value={openEvidence}>
      <div
        className="app"
        data-testid="app-root"
        data-case-id={c?.case_id ?? ""}
        aria-busy={attaching || busy === "run"}
      >
        <header className="hdr">
          <button
            className="wordmark"
            aria-label="ALIBI case library"
            onClick={() => {
              setTab("case");
              setShowLibrary(!!view);
            }}
          >
            ALIBI
            <span className="wordmark-rule" aria-hidden>
              {" "}
              /{" "}
            </span>
          </button>
          <nav className="tabs" aria-label="Workspace">
            <button
              data-testid="tab-case"
              className={tab === "case" ? "on" : ""}
              onClick={() => setTab("case")}
            >
              Workbench
            </button>
            <button
              data-testid="tab-benchmark"
              className={tab === "benchmark" ? "on" : ""}
              onClick={() => setTab("benchmark")}
            >
              Benchmark
            </button>
          </nav>
          <div className="badges">
            <span className="badge" data-testid="badge-inference">
              {c?.labels.inference_label ??
                (presets?.replays.length
                  ? "Offline replay available"
                  : "Case library")}
            </span>
            <span className="badge" data-testid="badge-evidence">
              {originLabel(c?.labels.evidence_origin ?? "SIM")}
            </span>
            {c && (
              <span className="badge playback" data-testid="badge-playback">
                {c.labels.playback === "REPLAY"
                  ? "REPLAY · recorded playback"
                  : c.labels.playback === "LIVE"
                    ? "LIVE · fresh case"
                    : c.labels.playback}
              </span>
            )}
          </div>
          <button
            data-testid="btn-details"
            onClick={() => setShowDetails(true)}
          >
            Details
          </button>
        </header>
        <section className="case-heading">
          <div>
            <p className="eyebrow" data-testid="case-eyebrow">
              {c
                ? `Case file / ${c.case_id.replace(/^case-/, "").slice(0, 8)}`
                : "An evidence workbench"}
              {c?.parent_case_id && " · reduced evidence view"}
              {c?.scored === false && " · imported evidence, unscored"}
            </p>
            <h1>{view ? title : "The log is missing. The evidence isn’t."}</h1>
          </div>
          <div className="heading-actions">
            {view ? (
              <>
                <button onClick={() => setShowLibrary(true)}>
                  Case library
                </button>
                <button
                  data-testid="btn-reset"
                  disabled={busy !== null}
                  onClick={doReset}
                >
                  {busy === "reset" ? "Resetting…" : "Reset"}
                </button>
              </>
            ) : (
              <button
                className="primary"
                data-testid="btn-run"
                disabled={busy !== null || !selected}
                onClick={() => doRun()}
              >
                {busy === "run" ? "Opening case…" : "Open selected case"}
              </button>
            )}
          </div>
        </section>
        {view && (
          <div className="case-subhead">
            <span>{view.card?.audience_setup ?? view.case.detail}</span>
            <ol className="workflow" aria-label="Case progress">
              <li
                className={!reviewPhase && state !== "scored" ? "current" : ""}
              >
                Investigation
              </li>
              <li className={reviewPhase ? "current" : ""}>Review</li>
              <li className={state === "scored" ? "current" : ""}>Reveal</li>
            </ol>
            <span className="statepill" data-testid="case-state">
              {humanState(state)}
            </span>
          </div>
        )}
        {!view && <span data-testid="case-state" />}
        {err && !failed && (
          <div className="banner err" role="alert" data-testid="error-banner">
            {err}
          </div>
        )}
        {bannerMsg && (
          <div className="banner err" role="alert" data-testid="error-banner">
            <span>
              {humanState(state)}: {bannerMsg}
            </span>
            {failed && (
              <button onClick={doReset} disabled={busy !== null}>
                Reset
              </button>
            )}
          </div>
        )}
        {disconnected && (
          <div className="banner" role="status" data-testid="connection-status">
            Connection interrupted. Retrying; your case and report are
            preserved.
          </div>
        )}
        {tab === "benchmark" ? (
          <main className="single">
            <BenchmarkTab />
          </main>
        ) : attaching && !view ? (
          <main className="single">
            <p role="status">
              Opening the saved case and restoring its evidence…
            </p>
          </main>
        ) : !view ? (
          <main className="single">
            <StartState
              presets={presets}
              err={presetErr}
              selected={selected}
              onSelect={setSelected}
              onRun={(choice) => doRun(choice)}
              busy={busy !== null}
              runtime={runtime}
              mode={mode}
              onMode={setMode}
              onDesign={() => {
                setShowLibrary(false);
                setShowDesigner(true);
              }}
            />
          </main>
        ) : (
          <>
            <main className="grid">
              <Sources
                view={view}
                selectedHost={selectedHost}
                onSelect={setSelectedHost}
                onOpenCase={doOpenCase}
              />
              <section
                className="col evidence-area"
                aria-label="Evidence comparison"
              >
                {view.case.parent_case_id && (
                  <ExperimentComparison view={view} />
                )}
                {view.case.card_id === "cold-chain" && hasReport(state) && (
                  <TemperatureRecords
                    caseId={view.case.case_id}
                    stateKey={view.manifest?.bundle_id ?? ""}
                  />
                )}
                {hasReport(state) ? (
                  <EvidenceColumn
                    caseId={view.case.case_id}
                    view={view}
                    run={run}
                    selectedHost={selectedHost}
                  />
                ) : (
                  <ProgressActivity run={run} state={state} />
                )}
                {view.report && <Ask caseId={view.case.case_id} />}
              </section>
              <CenterColumn
                view={view}
                run={run}
                busy={busy}
                reviewMsg={reviewMsg}
                onReview={doReview}
                onReveal={doReveal}
                onShowScore={() => setShowScore(true)}
              />
            </main>
            <QuestionPanel
              caseId={view.case.case_id}
              available={!!view.report}
              runtime={runtime}
            />
          </>
        )}
        {showLibrary && (
          <Dialog
            title="Case library"
            wide
            onClose={() => setShowLibrary(false)}
          >
            <p className="note">
              Opening another case preserves the current one. Its case URL will
              restore it.
            </p>
            <StartState
              presets={presets}
              err={presetErr}
              selected={selected}
              onSelect={setSelected}
              onRun={(choice) => doRun(choice)}
              busy={busy !== null}
              runtime={runtime}
              mode={mode}
              onMode={setMode}
              onDesign={() => {
                setShowLibrary(false);
                setShowDesigner(true);
              }}
            />
            <div className="modal-actions">
              {err && (
                <p role="alert" className="bad">
                  {err}
                </p>
              )}
              <button
                className="primary"
                disabled={busy !== null || !selected}
                onClick={() => doRun()}
              >
                {busy === "run" ? "Opening case…" : "Open selected case"}
              </button>
            </div>
          </Dialog>
        )}
        {showDesigner && (
          <Dialog
            title="Design an environment"
            onClose={() => setShowDesigner(false)}
          >
            <DesignerDialog
              runtime={runtime}
              mode={mode}
              onCase={(v) => {
                setShowDesigner(false);
                setTab("case");
                void attach(v.case.case_id, v);
              }}
            />
          </Dialog>
        )}
        {showDetails && (
          <Dialog title="Case details" onClose={() => setShowDetails(false)}>
            <RuntimeDetails view={view} run={run} runtime={runtime} />
          </Dialog>
        )}
        {raw && (
          <Dialog
            title="Raw evidence"
            wide
            onClose={() => {
              rawRequest.current += 1;
              setRaw(null);
            }}
          >
            <RawViewer raw={raw} />
          </Dialog>
        )}
        {state === "scored" && view?.reveal && showScore && (
          <ScoreOverlay
            view={view}
            run={run}
            onClose={() => setShowScore(false)}
          />
        )}
      </div>
    </EvidenceCtx.Provider>
  );
}

function StartState(p: {
  presets: Presets | null;
  err: string | null;
  selected: { kind: "preset" | "replay"; id: string } | null;
  onSelect: (s: { kind: "preset" | "replay"; id: string }) => void;
  onRun: (s: { kind: "preset" | "replay"; id: string }) => void;
  busy: boolean;
  runtime: Runtime | null;
  mode: string | null;
  onMode: (m: string) => void;
  onDesign: () => void;
}) {
  const modes = p.runtime?.capabilities?.investigation_modes;
  if (p.err)
    return (
      <div className="banner err" role="alert">
        Could not load the case library: {p.err}. Reload to reconnect.
      </div>
    );
  if (!p.presets)
    return (
      <p className="muted" role="status">
        Loading case library…
      </p>
    );
  const recommended = p.presets.replays.find(
    (x) => x.inference_mode === "RECORDED_MODEL",
  );
  return (
    <div className="start">
      <p className="library-intro">
        Compare the records that survived. Build a cited report. Lock your
        findings, then see what really happened.
      </p>
      {recommended && (
        <section className="featured-case">
          <div>
            <p className="eyebrow">Start here / recorded investigation</p>
            <h2>{recommended.title}</h2>
            <p>
              A local login record disappears. An independent collector keeps
              its copy. Follow the discrepancy from evidence to a human-reviewed
              report.
            </p>
            <div className="row wrap">
              <span className="tag">Recorded AI</span>
              <span className="tag">Simulated evidence</span>
              <span className="tag">Works offline</span>
            </div>
          </div>
          <div className="featured-action">
            <button
              className="primary"
              data-testid="btn-recorded-demo"
              disabled={p.busy}
              onClick={() => p.onRun({ kind: "replay", id: recommended.id })}
            >
              {p.busy ? "Opening…" : "Open recorded investigation"}
              <span aria-hidden> →</span>
            </button>
            <p className="small muted">
              {recommended.model_id}
              <br />
              Recorded outputs, no new model calls.
            </p>
          </div>
        </section>
      )}
      <div className="library-section-head">
        <div>
          <p className="eyebrow">Case library</p>
          <h2>Fresh investigations</h2>
        </div>
        <div>
          <p className="small muted">
            {p.runtime?.live_inference === "CONFIGURED"
              ? "Live AI configured. New cases use the server runtime."
              : "Fresh cases use a scripted fixture. Recorded AI works offline."}
          </p>
          {(modes?.available?.length ?? 0) > 1 && (
            <label className="small mode-picker">
              Investigation
              <select
                data-testid="mode-select"
                value={p.mode ?? modes?.default ?? ""}
                onChange={(e) => p.onMode(e.target.value)}
              >
                {(modes?.available ?? []).map((m) => (
                  <option key={m} value={m}>
                    {modes?.labels?.[m] ?? m}
                  </option>
                ))}
              </select>
            </label>
          )}
          {p.runtime?.capabilities?.scenario_designer?.endpoint && (
            <button
              className="linkish design-link"
              data-testid="btn-design"
              disabled={p.busy}
              onClick={p.onDesign}
            >
              Design an environment for a new case
            </button>
          )}
        </div>
      </div>
      <div className="cards">
        {p.presets.presets.map((x) => (
          <button
            key={x.id}
            data-testid={`preset-${x.id}`}
            className={`card ${p.selected?.id === x.id && p.selected.kind === "preset" ? "sel" : ""}`}
            aria-pressed={
              p.selected?.id === x.id && p.selected.kind === "preset"
            }
            onClick={() => p.onSelect({ kind: "preset", id: x.id })}
          >
            <span className="card-kicker">{x.difficulty} · Simulated</span>
            <b>{x.title}</b>
            <span>{x.blurb}</span>
            <span className="card-footer">
              {p.runtime?.live_inference === "CONFIGURED"
                ? "Live AI configured"
                : "Scripted fixture"}
              <span aria-hidden>↗</span>
            </span>
          </button>
        ))}
      </div>
      {p.presets.replays.length > 0 && (
        <>
          <h2 className="recordings-heading">Recorded replays</h2>
          <div className="replay-list">
            {p.presets.replays.map((x) => (
              <button
                key={x.id}
                data-testid={`replay-${x.id}`}
                className={`replay-row ${p.selected?.id === x.id && p.selected.kind === "replay" ? "sel" : ""}`}
                aria-pressed={
                  p.selected?.id === x.id && p.selected.kind === "replay"
                }
                onClick={() => p.onSelect({ kind: "replay", id: x.id })}
              >
                <b>{x.title}</b>
                <span>{x.inference_label ?? x.inference_mode}</span>
                <span className="small muted">{x.model_id}</span>
                <span className="tag">REPLAY</span>
              </button>
            ))}
          </div>
        </>
      )}
      {!p.presets.presets.length && !p.presets.replays.length && (
        <div className="empty-library">
          <h2>No cases available</h2>
          <p>
            The server has no presets or recordings. Add a case to the server,
            then reload this library.
          </p>
        </div>
      )}
    </div>
  );
}

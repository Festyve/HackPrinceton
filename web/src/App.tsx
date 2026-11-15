import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type {
  CaseInfo,
  CaseView,
  Presets,
  RawView,
  Runtime,
  ServerEvent,
} from "./api";
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
import { Navigation, CommandPalette, Pip } from "./shell";
import { CasesWorkspace } from "./case-files";
import type { Workspace, PaletteAction } from "./shell";
import { Lab, WorkerActivity } from "./lab";
import { LabExperiments } from "./lab-experiments";
import { useActionToken } from "./features/operation";
import { SavedComparison } from "./comparisons";
import {
  EvidenceInspector,
  InvestigationTools,
  PlanView,
  TraceView,
  CaseFile,
  Help,
} from "./investigation";
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
  "note_read",
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
  const [workspace, setWorkspace] = useState<Workspace>(
    hashId() ? "investigation" : "lab",
  );
  const workspaceRef = useRef(workspace);
  workspaceRef.current = workspace;
  const [palette, setPalette] = useState(false);
  const [pipOpen, setPipOpen] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [panelDialog, setPanelDialog] = useState<
    "plan" | "trace" | "notes" | null
  >(null);
  const [savedCases, setSavedCases] = useState<CaseInfo[]>([]);
  const [savedError, setSavedError] = useState(false);
  const [narrow, setNarrow] = useState(window.innerWidth < 900);
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
  const creation = useActionToken();

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
          if (tries < 8)
            window.setTimeout(loadRuntime, Math.min(1500 * tries, 8000));
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
    setWorkspace("cases");
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
      setWorkspace("investigation");
      setShowSources(false);
      setPanelDialog(null);
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
      setWorkspace("investigation");
      try {
        const requestToken = creation.take(
          `${choice.kind}:${choice.id}:${mode ?? "default"}`,
        );
        const v =
          choice.kind === "preset"
            ? await api.createCase(choice.id, mode, requestToken)
            : await api.openReplay(choice.id, requestToken);
        creation.done();
        await attach(v.case.case_id, v);
      } catch (e) {
        creation.done(e);
        throw e;
      }
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
  const doCancel = () =>
    guard("cancel", async () => {
      const id = caseIdRef.current;
      if (id) setView(await api.cancel(id));
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
    setShowSources(false);
    setPanelDialog(null);
    if (workspaceRef.current !== "lab") setWorkspace("investigation");
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

  useEffect(() => {
    let live = true;
    api
      .listCases()
      .then((r) => {
        if (live) {
          setSavedCases(r.cases);
          setSavedError(false);
        }
      })
      .catch(() => live && setSavedError(true));
    return () => {
      live = false;
    };
  }, [view?.case.case_id, view?.case.state]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
    };
    const onResize = () => setNarrow(window.innerWidth < 900);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, []);
  const c = view?.case;
  const state = c?.state ?? "";
  const labeledCase = workspace === "investigation" ? c : undefined;
  const failed = state === "failed" || state === "cancelled";
  const bannerMsg = failed ? c?.error || c?.detail || state : run.error;
  const title =
    (c?.lab ? c.title : view?.card?.title) ?? c?.title ?? "Case library";
  const reviewPhase = state === "awaiting_review" || state === "report_locked";
  const closeRaw = () => {
    rawRequest.current += 1;
    setRaw(null);
  };
  const libraryProps = {
    presets,
    err: presetErr,
    selected,
    onSelect: setSelected,
    onRun: (choice: { kind: "preset" | "replay"; id: string }) => doRun(choice),
    busy: busy !== null,
    runtime,
    mode,
    onMode: setMode,
    onDesign: () => {
      setShowLibrary(false);
      setShowDesigner(true);
    },
  };
  const actions: PaletteAction[] = [
    {
      id: "lab",
      title: "Open Lab",
      detail: "Configure a worker experiment",
      action: () => setWorkspace("lab"),
    },
    {
      id: "cases",
      title: "Open Cases",
      detail: "Recordings, original cases and captured evidence",
      action: () => setWorkspace("cases"),
    },
    {
      id: "experiments",
      title: "Open Experiments",
      detail: "Compare saved runs and measured results",
      action: () => setWorkspace("experiments"),
    },
    {
      id: "details",
      title: "Runtime and case details",
      detail: "Provenance, model, spend and hashes",
      action: () => setShowDetails(true),
    },
    ...(view
      ? [
          {
            id: "investigation",
            title: "Return to current investigation",
            detail: title,
            action: () => setWorkspace("investigation"),
          },
          {
            id: "review",
            title: "Inspect current report",
            detail: humanState(state),
            action: () => setWorkspace("investigation"),
          },
        ]
      : []),
    ...savedCases.map((item) => ({
      id: item.case_id,
      title: item.title ?? item.case_id,
      detail: `${item.case_id} · ${humanState(item.state)} · ${item.labels.inference_label}`,
      action: () => {
        void doOpenCase(item.case_id);
      },
    })),
  ];
  return (
    <EvidenceCtx.Provider value={openEvidence}>
      <div
        className="app"
        data-testid="app-root"
        data-case-id={c?.case_id ?? ""}
        data-workspace={workspace}
        data-case-family={c?.card_id ?? ""}
        aria-busy={attaching || busy === "run"}
      >
        <header className="hdr app-bar">
          <span className="window-dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="window-title">
            alibi —{" "}
            {workspace === "lab"
              ? "Lab"
              : workspace === "experiments"
                ? "Experiments"
                : workspace === "cases"
                  ? "Cases"
                  : "Investigator"}
          </span>
          <button
            className="command-trigger"
            data-testid="btn-command"
            onClick={() => setPalette(true)}
          >
            <span aria-hidden="true">⌕</span> Search cases & actions{" "}
            <kbd>⌘ K</kbd>
          </button>
          {!labeledCase && (
            <div className="badges">
              <span className="badge" data-testid="badge-inference">
                {presets?.replays.length
                  ? "Offline replay available"
                  : "Connecting to the lab"}
              </span>
            </div>
          )}
          <button
            data-testid="btn-details"
            onClick={() => setShowDetails(true)}
          >
            Details
          </button>
        </header>
        <div className="workspace-body">
          <Navigation
            current={workspace}
            onNavigate={setWorkspace}
            state={state}
            onHelp={() => setShowHelp(true)}
            cases={savedCases}
            onOpen={doOpenCase}
            onDetails={() => setShowDetails(true)}
          />
          <div className="workspace-content">
            <section className="case-heading">
              <div>
                <p className="eyebrow" data-testid="case-eyebrow">
                  {workspace === "lab"
                    ? "Worker lab · synthetic environment"
                    : workspace === "experiments"
                      ? "Change one condition"
                      : workspace === "cases"
                        ? "Recorded runs & frozen evidence"
                        : c
                          ? `Case file / ${c.case_id.replace(/^case-/, "").slice(0, 8)}`
                          : "Choose an investigation"}
                  {workspace === "investigation" &&
                    c?.parent_case_id &&
                    " · reduced evidence view"}
                  {workspace === "investigation" &&
                    c?.scored === false &&
                    " · imported evidence, unscored"}
                </p>
                <h1>
                  {workspace === "lab"
                    ? "Lab"
                    : workspace === "experiments"
                      ? "Experiments"
                      : workspace === "cases"
                        ? "Case library"
                        : view
                          ? title
                          : "Open a case to begin."}
                </h1>
                {labeledCase && (
                  <div
                    className="badges run-provenance"
                    role="group"
                    aria-label="Run provenance"
                  >
                    <span className="badge" data-testid="badge-inference">
                      {labeledCase?.labels.inference_label ??
                        (presets?.replays.length
                          ? "Offline replay available"
                          : "Connecting to the lab")}
                    </span>
                    {labeledCase && (
                      <span className="badge" data-testid="badge-evidence">
                        {originLabel(labeledCase.labels.evidence_origin)}
                      </span>
                    )}
                    {labeledCase && (
                      <span
                        className="badge playback"
                        data-testid="badge-playback"
                      >
                        {labeledCase.labels.playback === "REPLAY"
                          ? "REPLAY · recorded playback"
                          : labeledCase.labels.playback === "LIVE"
                            ? "LIVE · fresh case"
                            : labeledCase.labels.playback}
                      </span>
                    )}
                  </div>
                )}
              </div>
              <div className="heading-actions">
                {view && workspace === "investigation" ? (
                  <>
                    <button onClick={() => setShowLibrary(true)}>
                      Case library
                    </button>
                    {state === "investigating" &&
                      c?.labels.playback !== "REPLAY" && (
                        <button
                          data-testid="btn-cancel"
                          disabled={busy !== null}
                          onClick={doCancel}
                        >
                          {busy === "cancel"
                            ? "Requesting cancellation…"
                            : "Cancel investigation"}
                        </button>
                      )}
                    <button
                      data-testid="btn-reset"
                      disabled={busy !== null}
                      onClick={doReset}
                    >
                      {busy === "reset" ? "Resetting…" : "Reset"}
                    </button>
                  </>
                ) : workspace === "lab" && c?.lab ? (
                  <button
                    className="primary"
                    data-testid="btn-return-investigation"
                    onClick={() => setWorkspace("investigation")}
                  >
                    Open investigation <span aria-hidden="true">→</span>
                  </button>
                ) : workspace === "experiments" ? (
                  <button onClick={() => setWorkspace("cases")}>
                    Browse saved cases <span aria-hidden="true">↗</span>
                  </button>
                ) : workspace === "lab" &&
                  !selected &&
                  presets?.replays.some((x) => x.presentation_default) ? (
                  <button
                    className={
                      runtime?.capabilities?.worker_lab?.endpoint
                        ? ""
                        : "primary"
                    }
                    data-testid="btn-lab-replay"
                    disabled={busy !== null}
                    onClick={() => {
                      const r = presets.replays.find(
                        (x) => x.presentation_default,
                      );
                      if (r) void doRun({ kind: "replay", id: r.id });
                    }}
                  >
                    Open recorded investigation{" "}
                    <span aria-hidden="true">→</span>
                  </button>
                ) : (
                  <button
                    className={selected ? "primary" : ""}
                    data-testid="btn-run"
                    disabled={busy !== null || !selected}
                    onClick={() => doRun()}
                  >
                    {busy === "run" ? "Opening case…" : "Open selected case"}
                  </button>
                )}
              </div>
            </section>
            {err && !failed && (
              <div
                className="banner err"
                role="alert"
                data-testid="error-banner"
              >
                {err}
              </div>
            )}
            {bannerMsg && (
              <div
                className="banner err"
                role="alert"
                data-testid="error-banner"
              >
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
              <div
                className="banner"
                role="status"
                data-testid="connection-status"
              >
                Connection interrupted. Retrying; your case and report are
                preserved.
              </div>
            )}
            {workspace === "experiments" ? (
              <main className="single experiments-workspace">
                <LabExperiments
                  cases={savedCases}
                  currentId={c?.case_id}
                  runtime={runtime}
                  onOpen={doOpenCase}
                >
                  <SavedComparison cases={savedCases} onOpen={doOpenCase} />
                  <BenchmarkTab />
                </LabExperiments>
              </main>
            ) : workspace === "cases" || workspace === "lab" || !view ? (
              <main className="single library-workspace">
                {workspace === "lab" && (
                  <>
                    {c?.lab && (
                      <WorkerActivity
                        key={c.case_id}
                        caseId={c.case_id}
                        state={state}
                        onInvestigate={() => setWorkspace("investigation")}
                      />
                    )}
                    {c?.lab ? (
                      <details className="new-worker-experiment">
                        <summary>Configure another worker experiment</summary>
                        <Lab
                          runtime={runtime}
                          onCases={() => setWorkspace("cases")}
                          onCase={doOpenCase}
                        />
                      </details>
                    ) : (
                      <Lab
                        runtime={runtime}
                        onCases={() => setWorkspace("cases")}
                        onCase={doOpenCase}
                      />
                    )}
                  </>
                )}
                {workspace === "cases" && (
                  <CasesWorkspace
                    cases={savedCases}
                    casesError={savedError}
                    currentId={c?.case_id}
                    onOpen={doOpenCase}
                    {...libraryProps}
                  />
                )}
                {attaching && (
                  <p role="status">
                    Opening the saved case and restoring its evidence…
                  </p>
                )}
              </main>
            ) : (
              <>
                <div className="case-subhead">
                  <span>{view.card?.audience_setup ?? c?.detail}</span>
                  <ol className="workflow" aria-label="Case progress">
                    <li
                      className={
                        !reviewPhase && state !== "scored" ? "current" : ""
                      }
                    >
                      Investigation
                    </li>
                    <li className={reviewPhase ? "current" : ""}>Review</li>
                    <li className={state === "scored" ? "current" : ""}>
                      Reveal
                    </li>
                  </ol>
                  <span className="statepill" data-testid="case-state">
                    {humanState(state)}
                  </span>
                </div>
                {c?.lab && (
                  <div
                    className="worker-run-context"
                    data-testid="worker-provenance"
                  >
                    <div>
                      <span>
                        {c.labels.investigation_mode_label} ·{" "}
                        {c.labels.worker_choices}
                      </span>
                      <span>{c.labels.changed_objective_policy}</span>
                    </div>
                    <button onClick={() => setWorkspace("lab")}>
                      Inspect workers & activity ↗
                    </button>
                  </div>
                )}
                <InvestigationTools
                  hasCase={!!view}
                  planProgress={
                    run.todo.length
                      ? `${run.todo.filter((t) => t.status === "completed").length}/${run.todo.length}`
                      : undefined
                  }
                  onSources={() => setShowSources(true)}
                  onPlan={() => setPanelDialog("plan")}
                  onCaseFile={() => setPanelDialog("notes")}
                  onTrace={() => setPanelDialog("trace")}
                  onQuestions={() =>
                    document
                      .querySelector<HTMLInputElement>("#case-question")
                      ?.focus()
                  }
                />
                <div className="design-investigation-top">
                  <section className="design-card design-plan">
                    <header>
                      <h2>Plan</h2>
                      <span className="mono small muted">
                        {
                          run.todo.filter((t) => t.status === "completed")
                            .length
                        }{" "}
                        / {run.todo.length} done
                      </span>
                    </header>
                    <PlanView
                      key={view.case.case_id}
                      run={run}
                      caseId={view.case.case_id}
                      embedded
                    />
                  </section>
                  <section className="design-card design-activity">
                    <header>
                      <h2>Activity</h2>
                      <span className="mono small muted">
                        Recorded tool events
                      </span>
                    </header>
                    <TraceView
                      key={view.case.case_id}
                      run={run}
                      caseId={view.case.case_id}
                      embedded
                    />
                  </section>
                </div>
                <div
                  className={
                    "case-workspace" + (raw && !narrow ? " inspector-open" : "")
                  }
                >
                  <div className="case-content">
                    <main className="grid">
                      <section
                        className="col evidence-area"
                        aria-label="Evidence comparison"
                      >
                        {c?.parent_case_id && (
                          <ExperimentComparison view={view} />
                        )}
                        {c?.card_id === "cold-chain" && hasReport(state) && (
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
                  </div>
                  {raw && !narrow && (
                    <EvidenceInspector raw={raw} onClose={closeRaw} />
                  )}
                </div>
              </>
            )}
            {(workspace !== "investigation" || !view) && (
              <span className="sr-only" data-testid="case-state">
                {view ? humanState(state) : ""}
              </span>
            )}
          </div>
        </div>
        <div className="pip-dock">
          {pipOpen && (
            <section className="pip-feed" aria-label="Pip activity feed">
              <header>
                <span className="eyebrow">Investigator feed</span>
                <button
                  aria-label="Close Pip feed"
                  onClick={() => setPipOpen(false)}
                >
                  ×
                </button>
              </header>
              <p className="small muted">
                Recorded tool events · not hidden reasoning
              </p>
              {run.tools.length ? (
                run.tools.slice(-4).map((t) => (
                  <div key={t.seq}>
                    <span className="mono small amber">
                      #{t.seq} · {t.agent}
                    </span>
                    <p>{t.tool.replace(/_/g, " ")}</p>
                    <small>{t.ok ? "Completed" : "Error"}</small>
                  </div>
                ))
              ) : (
                <p className="small muted">No investigator activity yet.</p>
              )}
              <button
                onClick={() => {
                  setPipOpen(false);
                  if (view) setPanelDialog("trace");
                  else setWorkspace("cases");
                }}
              >
                {view ? "Open full trace" : "Open a saved case"} ↗
              </button>
            </section>
          )}
          <button
            className="pip-trigger"
            aria-expanded={pipOpen}
            onClick={() => setPipOpen((v) => !v)}
          >
            <Pip state={state} />
            <span>
              Pip
              <small>
                {state === "awaiting_review"
                  ? "Awaiting your review"
                  : state === "investigating"
                    ? "Investigating"
                    : state === "report_locked"
                      ? "Report locked"
                      : state === "scored"
                        ? "Report revealed"
                        : "Ready"}
              </small>
            </span>
            <span aria-hidden="true">{pipOpen ? "⌄" : "⌃"}</span>
          </button>
        </div>
        {palette && (
          <CommandPalette actions={actions} onClose={() => setPalette(false)} />
        )}
        {showHelp && <Help onClose={() => setShowHelp(false)} />}
        {showSources && view && (
          <Dialog
            title="Sources & witnesses"
            onClose={() => setShowSources(false)}
          >
            <Sources
              view={view}
              selectedHost={selectedHost}
              onSelect={setSelectedHost}
              onOpenCase={doOpenCase}
            />
          </Dialog>
        )}
        {panelDialog && view && (
          <Dialog
            title={
              panelDialog === "plan"
                ? "Investigation plan"
                : panelDialog === "trace"
                  ? "Investigation trace"
                  : "Case file"
            }
            wide
            onClose={() => setPanelDialog(null)}
          >
            {panelDialog === "plan" ? (
              <PlanView run={run} caseId={view.case.case_id} />
            ) : panelDialog === "trace" ? (
              <TraceView run={run} caseId={view.case.case_id} />
            ) : (
              <CaseFile view={view} run={run} />
            )}
          </Dialog>
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
            <StartState {...libraryProps} />
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
        {raw && (narrow || workspace === "lab") && (
          <Dialog title="Raw evidence" wide onClose={closeRaw}>
            <RawViewer raw={raw} />
          </Dialog>
        )}
        {state === "scored" &&
          view?.reveal &&
          showScore &&
          workspace === "investigation" && (
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
    (x) => x.presentation_default === true,
  );
  return (
    <div className="start">
      <p className="library-intro">
        Inspect a saved run, or investigate a frozen case. The original
        scenarios and captured bundles remain available alongside the new worker
        lab.
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

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import type { InvestigatorStep, StageEvent, StageView } from "./lab-api";

/* The audience's view of the sandbox, replayed from frozen evidence (GET /lab/stage).
   It never reads the sealed operator record. */

const IDLE_WORKERS = [
  { id: "W1", account: "wk-ingest", job: "ingest" },
  { id: "W2", account: "wk-report", job: "summarize" },
  { id: "W3", account: "wk-archive", job: "archive" },
];
const STATIONS: Array<{
  id: string;
  label: string;
  path: string;
  x: number;
  y: number;
}> = [
  { id: "raw", label: "raw datasets", path: "/srv/lab/raw/", x: 17, y: 17 },
  { id: "reports", label: "reports", path: "/srv/lab/reports/", x: 50, y: 17 },
  {
    id: "archive",
    label: "approved archive",
    path: "archive store",
    x: 83,
    y: 17,
  },
  { id: "tmp", label: "tmp exports", path: "/srv/lab/tmp/", x: 30, y: 80 },
  { id: "log", label: "local activity log", path: "access.log", x: 70, y: 80 },
];
const HOME: Record<string, { x: number; y: number }> = {
  W1: { x: 17, y: 50 },
  W2: { x: 50, y: 50 },
  W3: { x: 83, y: 50 },
};
const AT: Record<string, { x: number; y: number }> = {
  raw: { x: 17, y: 37 },
  reports: { x: 50, y: 37 },
  archive: { x: 83, y: 37 },
  tmp: { x: 30, y: 60 },
  log: { x: 70, y: 60 },
};
const clock = (t?: string | null) => (t ? t.slice(11, 19) : "");
const reduced = () =>
  typeof window !== "undefined" &&
  !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function WorkerFace({ red = false }: { red?: boolean }) {
  return (
    <span className={"bot" + (red ? " bot-red" : "")} aria-hidden="true">
      <i />
      <i />
    </span>
  );
}
export function InvestigatorFace() {
  return (
    <svg className="sleuth" viewBox="0 0 64 70" aria-hidden="true">
      <rect x="8" y="22" width="48" height="46" rx="11" fill="#4f8ff7" />
      <rect x="18" y="4" width="28" height="17" rx="5" fill="#27457e" />
      <rect x="2" y="18" width="60" height="7" rx="3.5" fill="#27457e" />
      <rect x="18" y="13" width="28" height="4" fill="#9cc0ff" />
      <circle
        cx="23"
        cy="42"
        r="8"
        fill="#eaf2ff"
        stroke="#10203f"
        strokeWidth="3"
      />
      <circle
        cx="41"
        cy="42"
        r="8"
        fill="#eaf2ff"
        stroke="#10203f"
        strokeWidth="3"
      />
      <path d="M31 42h2" stroke="#10203f" strokeWidth="3" />
      <circle className="sleuth-eye" cx="24" cy="42" r="2.6" fill="#10203f" />
      <circle className="sleuth-eye" cx="42" cy="42" r="2.6" fill="#10203f" />
    </svg>
  );
}

type Phase = "idle" | "workers" | "wait" | "inv" | "end";
// Where the investigator stands for each kind of check (scene percentages).
const INV_AT: Record<InvestigatorStep["station"], { x: number; y: number }> = {
  log: { x: 76, y: 66 },
  tmp: { x: 24, y: 66 },
  sched: { x: 50, y: 36 },
  center: { x: 50, y: 66 },
};

export function SandboxStage({
  stage,
  autoplay,
  playKey = 0,
  loading = false,
  checks = null,
  checksWaiting = false,
  onDone,
}: {
  stage: StageView | null;
  autoplay: boolean;
  playKey?: number;
  loading?: boolean;
  /** The investigator's recorded checks; null while its trace is not ready yet. */
  checks?: InvestigatorStep[] | null;
  checksWaiting?: boolean;
  onDone?: () => void;
}) {
  const events = useMemo<StageEvent[]>(() => {
    if (!stage) return [];
    return [
      ...stage.events.filter((e) => e.t !== null),
      ...stage.events.filter((e) => e.t === null),
    ];
  }, [stage]);
  const n = events.length;
  const m = checks?.length ?? 0;
  const [phase, setPhase] = useState<Phase>("idle");
  // step: index of the worker event being shown (n = all shown)
  const [step, setStep] = useState(-1);
  const [inv, setInv] = useState(0);
  useEffect(() => {
    if (!stage) {
      setPhase("idle");
      setStep(-1);
      return;
    }
    setInv(0);
    if (autoplay && !reduced() && n) {
      setStep(0);
      setPhase("workers");
    } else {
      setStep(n);
      setPhase("end");
    }
  }, [stage, autoplay, n, playKey]);
  // About 8 s for the workers however many events there are, then about 3.5 s for the investigator.
  const beat = Math.max(110, Math.min(1100, 8000 / Math.max(n, 1)));
  const invBeat = Math.max(450, Math.min(1100, 3600 / Math.max(m, 1)));
  const afterWorkers = () => {
    if (m) {
      setInv(0);
      setPhase("inv");
    } else setPhase(checks === null && checksWaiting ? "wait" : "end");
  };
  useEffect(() => {
    if (phase !== "workers") return;
    if (step >= n) {
      afterWorkers();
      return;
    }
    const id = window.setTimeout(() => setStep((s) => s + 1), beat);
    return () => window.clearTimeout(id);
  }, [phase, step, n, beat]);
  useEffect(() => {
    if (phase !== "wait") return;
    if (m) {
      setInv(0);
      setPhase("inv");
    } else if (!checksWaiting) setPhase("end");
  }, [phase, m, checksWaiting]);
  useEffect(() => {
    if (phase !== "inv") return;
    if (inv >= m) {
      setPhase("end");
      return;
    }
    const id = window.setTimeout(() => setInv((i) => i + 1), invBeat);
    return () => window.clearTimeout(id);
  }, [phase, inv, m, invBeat]);
  useEffect(() => {
    if (phase === "end") onDone?.();
  }, [phase]);

  const workers = stage?.workers ?? IDLE_WORKERS;
  const k = workers.length;
  const home = (id: string, i: number) =>
    (k <= 3 && HOME[id]) || { x: ((i + 1) * 100) / (k + 1), y: 50 };
  const homeOf = (id: string) =>
    home(
      id,
      Math.max(
        0,
        workers.findIndex((w) => w.id === id),
      ),
    );
  const shown = events.slice(0, Math.min(step + 1, n));
  const now = phase === "workers" && step >= 0 && step < n ? events[step] : null;
  const check = phase === "inv" && inv < m && checks ? checks[inv] : null;
  const red = new Set(
    shown.filter((e) => e.kind !== "routine").map((e) => e.worker),
  );
  const gone = new Set(
    shown
      .filter((e) => e.kind === "local_record_missing")
      .map((e) => e.evidence_id),
  );
  const flagged = shown.filter((e) => e.kind === "unassigned");
  const timed = shown.filter((e) => e.t !== null);
  const collector = timed.filter((e) => e.kept_by_collector).length;
  const local = timed.length - gone.size;
  const playing = phase === "workers" || phase === "wait" || phase === "inv";
  const done = !!stage && phase === "end";
  const investigatorIn = phase === "inv" || phase === "wait";
  const caption = !stage
    ? loading
      ? "preparing sandbox…"
      : ""
    : now
      ? now.kind === "local_record_missing"
        ? `${now.worker} erases log line ${clock(now.line_t)} · collector keeps its copy`
        : `${now.worker} ${now.action.replace(/_/g, " ")} ${now.dataset ?? ""}${now.kind === "unassigned" ? " · unassigned" : ""}`
      : phase === "wait"
        ? "Investigator starting…"
        : check
          ? `Investigator · ${check.caption}`
          : "done";
  const invPos = check ? INV_AT[check.station] : INV_AT.center;
  return (
    <section
      className={
        "vm" + (playing ? " vm-playing" : "") + (!stage ? " vm-idle" : "")
      }
      data-testid="sandbox-stage"
      data-stage={!stage ? "idle" : done ? "done" : "playing"}
      data-phase={phase}
      aria-label="Sandbox stage"
    >
      <header className="vm-bar">
        <span className="vm-prompt">
          <b>lab@sandbox</b>:~${" "}
          {stage ? "replay --from frozen-evidence" : "watch workers"}
        </span>
        <span className="vm-tools">
          {stage && (
            <>
              <button
                type="button"
                data-testid="btn-stage-replay"
                disabled={!n}
                onClick={() => {
                  setInv(0);
                  setStep(0);
                  setPhase("workers");
                }}
              >
                ↻ Replay
              </button>
              <button
                type="button"
                data-testid="btn-stage-skip"
                disabled={!playing}
                onClick={() => {
                  setStep(n);
                  setPhase("end");
                }}
              >
                Skip ⏭
              </button>
            </>
          )}
          <span className="vm-state">
            {!stage
              ? "IDLE"
              : phase === "workers"
                ? "WORKERS"
                : investigatorIn
                  ? "INVESTIGATOR"
                  : "END"}
          </span>
        </span>
      </header>
      <div className="vm-outside">
        <div className={"vm-sleuth" + (investigatorIn ? " away" : "")}>
          <span>Investigator</span>
          <InvestigatorFace />
        </div>
        <div
          className={
            "vm-collector" +
            (collector ? " has" : "") +
            (check?.collector ? " checked" : "")
          }
        >
          <span className="vm-collector-n" data-testid="collector-count">
            {collector}
          </span>
          <div>
            <b>Collector</b>
          </div>
        </div>
      </div>
      <div className="vm-scene">
        <span className="vm-boundary-label">sandbox boundary</span>
        {STATIONS.map((s) => (
          <div
            key={s.id}
            className={
              "vm-station vm-station-" +
              s.id +
              (now?.station === s.id || check?.station === s.id
                ? " active"
                : "") +
              (now?.station === s.id && now.kind !== "routine" ? " alert" : "")
            }
            style={{ left: `${s.x}%`, top: `${s.y}%` }}
          >
            <b>{s.label}</b>
            <small>{s.path}</small>
            {s.id === "log" && stage && (
              <div className="vm-log">
                <span>
                  local {local} · collector {collector}
                </span>
                {flagged.slice(-4).map((e) => (
                  <code
                    key={e.evidence_id}
                    className={gone.has(e.evidence_id) ? "gone" : ""}
                  >
                    {gone.has(e.evidence_id)
                      ? `${clock(e.t)} missing`
                      : `${clock(e.t)} ${e.action}`}
                  </code>
                ))}
              </div>
            )}
          </div>
        ))}
        {workers.map((w, i) => {
          const mine = now?.worker === w.id ? now : null;
          const pos = (mine && AT[mine.station]) || home(w.id, i);
          const isRed = red.has(w.id);
          const checked = check?.station === "sched";
          return (
            <div
              key={w.id}
              className={
                "vm-worker" +
                (mine ? " busy" : "") +
                (isRed ? " red" : "") +
                (checked ? " checked" : "")
              }
              data-worker={w.id}
              data-red={isRed ? "true" : "false"}
              style={
                {
                  left: `${pos.x}%`,
                  top: `${pos.y}%`,
                  transitionDuration: `${Math.round(beat * 0.5)}ms`,
                  "--d": `${i * 0.4}s`,
                } as CSSProperties
              }
            >
              <WorkerFace red={isRed} />
              {mine?.kind === "unassigned" && (
                <em className="vm-carry">{mine.dataset}</em>
              )}
              <span>
                {w.id} <small>{w.job}</small>
              </span>
            </div>
          );
        })}
        {investigatorIn && (
          <div
            className="vm-inv"
            data-testid="stage-investigator"
            data-station={check?.station ?? "entering"}
            style={{ left: `${invPos.x}%`, top: `${invPos.y}%` }}
          >
            <InvestigatorFace />
            {check?.delegate && (
              <span
                className="vm-inv-delegate"
                data-testid="stage-delegate"
                title={check.delegate}
              >
                <i aria-hidden="true" />
                {check.delegate.replace(/[-_]/g, " ")}
              </span>
            )}
          </div>
        )}
        {now && now.t !== null && now.kept_by_collector && (
          <i
            key={step}
            className={"vm-packet" + (now.kind !== "routine" ? " red" : "")}
            style={
              {
                "--fx": `${(AT[now.station] ?? homeOf(now.worker)).x}%`,
                "--fy": `${(AT[now.station] ?? homeOf(now.worker)).y}%`,
                animationDuration: `${Math.round(beat * 0.8)}ms`,
              } as CSSProperties
            }
          />
        )}
      </div>
      <footer className="vm-foot">
        <span className="vm-caption" data-testid="stage-caption">
          {caption && <b>&gt;</b>} {caption}
        </span>
        <small data-testid="stage-label">{stage?.label ?? ""}</small>
      </footer>
    </section>
  );
}

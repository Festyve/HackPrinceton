import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import type { StageEvent, StageView } from "./lab-api";

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

export function SandboxStage({
  stage,
  autoplay,
  loading = false,
  onDone,
}: {
  stage: StageView | null;
  autoplay: boolean;
  loading?: boolean;
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
  // step: -1 idle, 0..n-1 the event being shown, n the end state
  const [step, setStep] = useState(-1);
  useEffect(() => {
    if (!stage) {
      setStep(-1);
      return;
    }
    setStep(autoplay && !reduced() && n ? 0 : n);
  }, [stage, autoplay, n]);
  const beat = Math.max(380, Math.min(1100, 10000 / Math.max(n, 1)));
  useEffect(() => {
    if (!stage || step < 0) return;
    if (step >= n) {
      onDone?.();
      return;
    }
    const id = window.setTimeout(() => setStep((s) => s + 1), beat);
    return () => window.clearTimeout(id);
  }, [stage, step, n, beat]);

  const workers = stage?.workers ?? IDLE_WORKERS;
  const shown = events.slice(0, Math.min(step + 1, n));
  const now = step >= 0 && step < n ? events[step] : null;
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
  const playing = !!now;
  const done = !!stage && step >= n;
  const caption = !stage
    ? loading
      ? "preparing sandbox…"
      : "idle · no run yet"
    : now
      ? now.kind === "local_record_missing"
        ? `${now.worker} · log line ${clock(now.line_t)} · Local: missing · Collector: retained`
        : `${now.worker} ${now.action.replace(/_/g, " ")} ${now.dataset ?? ""}${now.kind === "unassigned" ? " · unassigned" : ""}`
      : stage.summary.unassigned || stage.summary.local_records_missing
        ? `done · ${stage.summary.routine} routine · ${stage.summary.unassigned} unassigned · ${stage.summary.local_records_missing} local records missing`
        : `done · ${stage.summary.routine} routine · nothing unassigned`;
  return (
    <section
      className={
        "vm" + (playing ? " vm-playing" : "") + (!stage ? " vm-idle" : "")
      }
      data-testid="sandbox-stage"
      data-stage={!stage ? "idle" : done ? "done" : "playing"}
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
                onClick={() => setStep(0)}
              >
                ↻ Replay
              </button>
              <button
                type="button"
                data-testid="btn-stage-skip"
                disabled={!playing}
                onClick={() => setStep(n)}
              >
                Skip ⏭
              </button>
            </>
          )}
          <span className="vm-state">
            {!stage ? "IDLE" : playing ? "REPLAY" : "END"}
          </span>
        </span>
      </header>
      <div className="vm-outside">
        <div className="vm-sleuth">
          <span>Investigator</span>
          <InvestigatorFace />
        </div>
        <div className={"vm-collector" + (collector ? " has" : "")}>
          <span className="vm-collector-n" data-testid="collector-count">
            {collector}
          </span>
          <div>
            <b>Collector</b>
            <small>beyond the workers’ reach</small>
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
              (now?.station === s.id ? " active" : "") +
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
                {flagged.map((e) => (
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
          const pos = (mine && AT[mine.station]) ||
            HOME[w.id] || { x: 20 + i * 30, y: 54 };
          const isRed = red.has(w.id);
          return (
            <div
              key={w.id}
              className={
                "vm-worker" + (mine ? " busy" : "") + (isRed ? " red" : "")
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
        {now && now.t !== null && now.kept_by_collector && (
          <i
            key={step}
            className={"vm-packet" + (now.kind !== "routine" ? " red" : "")}
            style={
              {
                "--fx": `${(AT[now.station] ?? HOME[now.worker]).x}%`,
                "--fy": `${(AT[now.station] ?? HOME[now.worker]).y}%`,
                animationDuration: `${Math.round(beat * 0.8)}ms`,
              } as CSSProperties
            }
          />
        )}
      </div>
      <footer className="vm-foot">
        <span className="vm-caption" data-testid="stage-caption">
          <b>&gt;</b> {caption}
        </span>
        <small data-testid="stage-label">{stage?.label ?? ""}</small>
      </footer>
    </section>
  );
}

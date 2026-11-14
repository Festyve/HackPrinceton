import { useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { CaseView, Compare, CompareRow, RawView, Timeline } from "./api";
import type { Run } from "./model";
import { short } from "./model";
import { EvidenceCtx, hhmmss } from "./common";
import type { RawTarget } from "./App";

interface RawState { loading: boolean; error: string | null; data: RawView | null; eventId?: string }

export function EvidenceColumn({ caseId, view, run, raw }: { caseId: string; view: CaseView; run: Run; raw: RawState | null }) {
  const policy = (view.manifest?.operational_context as { logging_policy?: { forwarded_files?: Array<{ host: string; file: string }> } } | undefined)?.logging_policy;
  const files = policy?.forwarded_files ?? [];
  const [sel, setSel] = useState("workstation|/var/log/auth.log");
  const hasDefault = files.some((f) => `${f.host}|${f.file}` === "workstation|/var/log/auth.log");
  const effective = hasDefault || !files.length ? sel : `${files[0].host}|${files[0].file}`;
  const [host, file] = effective.split("|");
  const findingIds = Object.keys(run.findings);
  return (
    <section className="col right">
      <h2>Evidence</h2>
      {files.length > 1 && (
        <label className="small">Forwarded file{" "}
          <select value={effective} onChange={(e) => setSel(e.target.value)}>
            {files.map((f) => <option key={f.host + f.file} value={`${f.host}|${f.file}`}>{f.host} {f.file}</option>)}
          </select>
        </label>
      )}
      <CompareTable key={caseId + effective} caseId={caseId} host={host} file={file} stateKey={view.case.state === "scored" ? "s" : "r"} />
      <RawViewer raw={raw} />
      <TimelineView caseId={caseId} refresh={findingIds.length} />
    </section>
  );
}

const STATUS: Record<string, { word: string; glyph: string; cls: string }> = {
  both: { word: "in both copies", glyph: "=", cls: "both" },
  retained_by_collector: { word: "retained by collector", glyph: "⚠", cls: "retained" },
  rotated_out: { word: "rotated out (expected)", glyph: "↻", cls: "rotated" },
  local_only: { word: "never reached the collector", glyph: "◇", cls: "localonly" },
  inconclusive: { word: "inconclusive", glyph: "?", cls: "inconc" },
  collector_only: { word: "collector only", glyph: "◆", cls: "collonly" },
};

function CompareTable({ caseId, host, file, stateKey }: { caseId: string; host: string; file: string; stateKey: string }) {
  const [data, setData] = useState<Compare | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const open = useContext(EvidenceCtx);
  useEffect(() => {
    let live = true;
    setData(null); setErr(null);
    api.compare(caseId, host, file).then((d) => live && setData(d)).catch((e: unknown) => live && setErr(e instanceof Error ? e.message : String(e)));
    return () => { live = false; };
  }, [caseId, host, file, stateKey]);

  const rows = useMemo(() => {
    if (!data) return [] as CompareRow[];
    if (all) return data.rows;
    const interesting = (r: CompareRow) => r.status !== "both" && r.status !== "rotated_out";
    const keep = new Set<number>();
    data.rows.forEach((r, i) => { if (interesting(r) || r.focus) { keep.add(i - 1); keep.add(i); keep.add(i + 1); } });
    return data.rows.filter((r, i) => keep.has(i) && r.status !== "rotated_out");
  }, [data, all]);

  const missing = data?.counts.retained_by_collector ?? 0;
  return (
    <div className="panel compare">
      <h3>Host log vs collector <small className="mono">{host} {file}</small></h3>
      {err && <div className="banner err small">{err}</div>}
      {!data && !err && <p className="muted">Loading comparison…</p>}
      {data && (
        <>
          <p className={"headline " + (missing ? "bad" : "ok")}>
            {missing
              ? `⚠ ${missing} line${missing === 1 ? "" : "s"} present at the collector, absent from the host's own log`
              : "✓ No unexplained absence: every collector line is in the host log or explained by rotation"}
          </p>
          <p className="small muted">
            Counts: {Object.entries(data.counts).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}.
            {data.local_coverage_start && <> Host log coverage starts {data.local_coverage_start} (basis: {data.coverage_basis ?? "unspecified"}).</>}
          </p>
          <div className="tablewrap">
            <table data-testid="compare-table">
              <thead><tr><th>Time</th><th>Host's own log</th><th>Collector copy</th></tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  const m = STATUS[r.status] ?? { word: r.status, glyph: "•", cls: "other" };
                  const hostCell = r.status === "retained_by_collector"
                    ? <td className="hatch"><b>{"✖"} absent from host log</b></td>
                    : r.local
                      ? <td><button className="line mono" onClick={() => open({ artifact: r.local!.artifact, line: r.local!.line, eventId: r.local!.event_id } as RawTarget)}>{r.text}</button></td>
                      : <td className="hatch muted">not in host log</td>;
                  const collCell = r.collector
                    ? <td><button className="line mono" onClick={() => open({ artifact: r.collector!.artifact, line: r.collector!.line, eventId: r.collector!.event_id } as RawTarget)}>{r.text}</button></td>
                    : <td className="muted">{r.status === "local_only" ? "—" : "not at collector"}</td>;
                  return (
                    <tr key={i} className={"row-" + m.cls + (r.focus ? " focus" : "")} data-testid={r.status === "retained_by_collector" ? "compare-row-retained" : undefined}>
                      <td className="mono small nowrap">{hhmmss(r.ts)}<div className={"tag s-" + m.cls}>{m.glyph} {m.word}</div></td>
                      {hostCell}
                      {collCell}
                    </tr>
                  );
                })}
                {rows.length === 0 && <tr><td colSpan={3} className="muted">Nothing to show.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="row small">
            <button onClick={() => setAll(!all)}>{all ? "Show only the discrepancy and context" : `Show all ${data.rows.length} rows`}</button>
          </div>
          {data.legend && (
            <details className="small"><summary>Legend</summary>
              <ul>{Object.entries(data.legend).map(([k, v]) => <li key={k}><b>{STATUS[k]?.word ?? k}</b>: {v}</li>)}</ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function RawViewer({ raw }: { raw: RawState | null }) {
  return (
    <div className="panel" data-testid="raw-viewer">
      <h3>Raw record viewer</h3>
      {!raw && <p className="muted">Click any evidence chip or log line to see it here in its source file.</p>}
      {raw?.loading && <p className="muted">Loading…</p>}
      {raw?.error && <div className="banner err small">{raw.error}</div>}
      {raw?.data && (
        <>
          <div className="small">
            <span className="mono">{raw.data.artifact}</span> · {raw.data.host} / {raw.data.source} · sha256 <span className="mono">{short(raw.data.sha256)}</span>
          </div>
          <div className={"tag " + (raw.data.tamper_exposure === "independent_witness" ? "witness" : "local")}>
            {raw.data.tamper_exposure === "independent_witness" ? "◆ independent witness" : "◇ host‑local, adversary‑writable in this model"}
          </div>
          {raw.data.coverage_note && <div className="small muted">{raw.data.coverage_note}</div>}
          <pre className="raw">
            {raw.data.lines.map((l) => (
              <div key={l.n} className={l.focus ? "focusline" : ""} data-testid={l.focus ? "raw-focus-line" : undefined}>
                <span className="ln">{l.n}</span>{l.focus ? "▶ " : "  "}{l.text}
              </div>
            ))}
          </pre>
          <div className="small muted">line {raw.data.focus_line} of {raw.data.total_lines}</div>
        </>
      )}
    </div>
  );
}

function TimelineView({ caseId, refresh }: { caseId: string; refresh: number }) {
  const [t, setT] = useState<Timeline | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const open = useContext(EvidenceCtx);
  useEffect(() => {
    let live = true;
    api.timeline(caseId).then((d) => live && setT(d)).catch((e: unknown) => live && setErr(e instanceof Error ? e.message : String(e)));
    return () => { live = false; };
  }, [caseId, refresh]);
  if (err) return <div className="panel" data-testid="timeline"><h3>Timeline</h3><div className="banner err small">{err}</div></div>;
  if (!t) return <div className="panel" data-testid="timeline"><h3>Timeline</h3><p className="muted">Loading…</p></div>;
  const t0 = Date.parse(t.start), t1 = Date.parse(t.end), span = Math.max(1, t1 - t0);
  const pct = (iso: string) => Math.min(100, Math.max(0, ((Date.parse(iso) - t0) / span) * 100));
  return (
    <div className="panel" data-testid="timeline">
      <h3>Timeline <small>{hhmmss(t.start)} to {hhmmss(t.end)} UTC</small></h3>
      {t.lanes.map((l) => {
        const max = Math.max(1, ...l.counts);
        return (
          <div key={l.key} className="lane">
            <div className="lanelabel small">
              {l.independent_witness ? "◆" : "◇"} {l.label} <span className="muted">({l.total})</span>
            </div>
            <div className="track">
              <div className="bars">
                {l.counts.map((c, i) => <i key={i} style={{ height: `${(c / max) * 100}%` }} />)}
              </div>
              {l.gaps.map((g, i) => (
                <span key={i} className={"gap g-" + g.kind} title={`${g.kind}: ${g.label}`}
                  style={{ left: pct(g.start) + "%", width: `max(6px, ${Math.max(0, pct(g.end) - pct(g.start))}%)` }} />
              ))}
              {l.marks.map((m, i) => (
                <button key={i} className="mark" title={`cited evidence ${m.event_id} (${m.finding_ids.join(", ")})`}
                  style={{ left: pct(m.ts) + "%" }} onClick={() => open(m.event_id)}>{"▼"}</button>
              ))}
            </div>
            {l.gaps.length > 0 && (
              <div className="small gaplist">
                {l.gaps.map((g, i) => <span key={i} className={"tag g-" + g.kind}>{"▓"} {g.kind.replace(/_/g, " ")}: {g.label}</span>)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

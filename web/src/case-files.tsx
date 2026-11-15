import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { CaseInfo, Presets, Runtime } from "./api";
import { filesApi } from "./files-api";
import type { CaseFileEntry, CaseFileListing } from "./files-api";
import { humanState } from "./workbench";
import { message } from "./features/operation";

type Choice = { kind: "preset" | "replay"; id: string };

/* ------------------------------------------------------------------ Markdown, rendered as React nodes only */

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null) out.push(<code key={m.index}>{m[1]}</code>);
    else if (m[2] != null) out.push(<b key={m.index}>{inline(m[2])}</b>);
    else out.push(<em key={m.index}>{m[3]}</em>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
const cells = (line: string) =>
  line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
const LIST = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const k = out.length;
    if (!line.trim()) {
      i++;
    } else if (line.startsWith("```")) {
      const code: string[] = [];
      for (i++; i < lines.length && !lines[i].startsWith("```"); i++)
        code.push(lines[i]);
      i++;
      out.push(<pre key={k}>{code.join("\n")}</pre>);
    } else if (/^#{1,6}\s/.test(line)) {
      const level = /^#+/.exec(line)![0].length;
      const body = inline(line.replace(/^#+\s+/, ""));
      out.push(
        level === 1 ? (
          <h2 key={k}>{body}</h2>
        ) : level === 2 ? (
          <h3 key={k}>{body}</h3>
        ) : (
          <h4 key={k}>{body}</h4>
        ),
      );
      i++;
    } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push(<hr key={k} />);
      i++;
    } else if (
      line.trim().startsWith("|") &&
      /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1] ?? "") &&
      (lines[i + 1] ?? "").includes("-")
    ) {
      const head = cells(line);
      const body: string[][] = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i++)
        body.push(cells(lines[i]));
      out.push(
        <div className="md-table" key={k}>
          <table>
            {head.some(Boolean) && (
              <thead>
                <tr>
                  {head.map((c, j) => (
                    <th key={j}>{inline(c)}</th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {body.map((row, r) => (
                <tr key={r}>
                  {row.map((c, j) => (
                    <td key={j}>{inline(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
    } else if (LIST.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: ReactNode[] = [];
      for (; i < lines.length && LIST.test(lines[i]); i++) {
        const [, pad, , rest] = LIST.exec(lines[i])!;
        const box = /^\[([ xX~])\]\s+(.*)$/.exec(rest);
        items.push(
          <li
            key={i}
            className={box ? "md-task" : ""}
            style={pad.length >= 2 ? { marginLeft: 20 } : undefined}
          >
            {box ? (
              <>
                <span
                  className={`md-box ${box[1] === " " ? "" : box[1] === "~" ? "doing" : "done"}`}
                  role="img"
                  aria-label={
                    box[1] === " "
                      ? "not started"
                      : box[1] === "~"
                        ? "in progress"
                        : "done"
                  }
                >
                  {box[1] === " " ? "" : box[1] === "~" ? "–" : "✓"}
                </span>
                {inline(box[2])}
              </>
            ) : (
              inline(rest)
            )}
          </li>,
        );
      }
      out.push(ordered ? <ol key={k}>{items}</ol> : <ul key={k}>{items}</ul>);
    } else if (line.startsWith(">")) {
      const quote: string[] = [];
      for (; i < lines.length && lines[i].startsWith(">"); i++)
        quote.push(lines[i].replace(/^>\s?/, ""));
      out.push(<blockquote key={k}>{inline(quote.join(" "))}</blockquote>);
    } else {
      const para: string[] = [];
      for (
        ;
        i < lines.length &&
        lines[i].trim() &&
        !/^(#{1,6}\s|```|>|\s*\|)/.test(lines[i]) &&
        !LIST.test(lines[i]);
        i++
      )
        para.push(lines[i]);
      if (!para.length) para.push(lines[i++]);
      out.push(<p key={k}>{inline(para.join(" "))}</p>);
    }
  }
  return <div className="md">{out}</div>;
}

/* ------------------------------------------------------------------ icons */

const Icon = ({ d }: { d: string }) => (
  <svg
    viewBox="0 0 16 16"
    width="16"
    height="16"
    aria-hidden="true"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.3"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d={d} />
  </svg>
);
const FOLDER = "M1.500 4.500a1 1 0 011-1h3l1.500 1.500h6.500a1 1 0 011 1v6.500a1 1 0 01-1 1h-11a1 1 0 01-1-1z";
const FILE = "M4 1.500h5l3 3v10H4zM9 1.500v3h3M6 8h4M6 10.500h4";
const BRACES =
  "M6 2.500c-1.500 0-2 .7-2 2v1.500c0 1-.5 1.500-1.500 2 1 .5 1.500 1 1.500 2V11.500c0 1.300.5 2 2 2M10 2.500c1.500 0 2 .7 2 2v1.500c0 1 .5 1.500 1.500 2-1 .5-1.500 1-1.500 2V11.500c0 1.300-.5 2-2 2";

/* ------------------------------------------------------------------ one case's files */

/** The first file worth reading: the agent's notes, then its plan, then the report. Never raw JSON first. */
function firstReadable(l: CaseFileListing): string | null {
  const ok = (f: CaseFileEntry) => f.available && f.kind === "markdown";
  return (
    l.files.find((f) => ok(f) && f.path.startsWith("notes/") && f.path !== "notes/")?.path ??
    l.files.find((f) => ok(f) && f.path === "plan.md")?.path ??
    l.files.find((f) => ok(f) && f.path === "report.md")?.path ??
    l.files.find(ok)?.path ??
    null
  );
}

function FileBrowser({ caseId }: { caseId: string }) {
  const [listing, setListing] = useState<CaseFileListing | null>(null);
  const [path, setPath] = useState<string | null>(null);
  const [file, setFile] = useState<{ path: string; content: string } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    filesApi
      .list(caseId)
      .then((l) => {
        if (!live || l.case_id !== caseId) return;
        setListing(l);
        setError(null);
        const ok = (p: string) => l.files.some((f) => f.path === p && f.available);
        setPath((old) => (old && ok(old) && tick > 0 ? old : firstReadable(l)));
      })
      .catch((e) => live && setError(message(e)));
    return () => {
      live = false;
    };
  }, [caseId, tick]);
  useEffect(() => {
    setFile(null);
    setCopied(false);
    if (!path) return;
    let live = true;
    filesApi
      .content(caseId, path)
      .then((c) => {
        if (live && c.case_id === caseId && c.path === path)
          setFile({ path, content: c.content });
      })
      .catch((e) => live && setError(message(e)));
    return () => {
      live = false;
    };
  }, [caseId, path, tick]);
  const entry = listing?.files.find((f) => f.path === path);
  const shown = file && file.path === path ? file : null;
  const top = listing?.files.filter((f) => !f.path.includes("/")) ?? [];
  const folders = ["notes", "evidence"]
    .map((name) => ({
      name,
      files: listing?.files.filter((f) => f.path.startsWith(name + "/")) ?? [],
    }))
    .filter((f) => f.files.length);
  const row = (f: CaseFileEntry, nested = false) => {
    const name = f.path.split("/").pop() || "no files";
    return (
      <li key={f.path} className={nested ? "nested" : ""}>
        <button
          className={`cf-file ${f.path === path ? "sel" : ""}`}
          data-file={f.path}
          disabled={!f.available}
          aria-current={f.path === path ? "true" : undefined}
          title={f.available ? f.title : (f.reason ?? "unavailable")}
          onClick={() => setPath(f.path)}
        >
          <Icon d={f.kind === "json" ? BRACES : FILE} />
          <span>
            {name}
            {!f.available && <small>{f.reason ?? "unavailable"}</small>}
          </span>
        </button>
      </li>
    );
  };
  return (
    <div
      className="cf"
      data-testid="case-files"
      data-case-id={caseId}
      title={listing?.note}
    >
      {error && (
        <p role="alert" className="cf-error">
          {error}
        </p>
      )}
      <div className="cf-body">
        <nav
          className="cf-tree"
          data-testid="case-file-tree"
          aria-label="Case files"
        >
          {!listing && !error && <p role="status">Loading…</p>}
          <ul>
            {folders.map((folder) => (
              <li key={folder.name}>
                <span className="cf-folder">
                  <Icon d={FOLDER} />
                  {folder.name}
                </span>
                <ul>{folder.files.map((f) => row(f, true))}</ul>
              </li>
            ))}
            {top.map((f) => row(f))}
          </ul>
          <button
            className="linkish cf-refresh"
            data-testid="case-files-refresh"
            onClick={() => setTick((t) => t + 1)}
          >
            Refresh
          </button>
        </nav>
        <section
          className="cf-preview"
          data-testid="case-file-preview"
          data-path={shown?.path ?? ""}
          aria-label="File preview"
        >
          {entry && (
            <div className="cf-bar">
              <span className="mono">{entry.path}</span>
              <button
                disabled={!shown}
                onClick={() => {
                  if (!shown) return;
                  void navigator.clipboard
                    ?.writeText(shown.content)
                    .then(() => setCopied(true))
                    .catch(() => undefined);
                }}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          )}
          <div className="cf-content">
            {!entry ? (
              listing && <p className="cf-none">Pick a file.</p>
            ) : !shown ? (
              <p role="status">Loading…</p>
            ) : entry.kind === "markdown" ? (
              <Markdown text={shown.content} />
            ) : (
              <pre className="cf-code">{shown.content}</pre>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ one run, as a row */

const MODE: Record<string, string> = { fast: "Solo", specialist: "Specialists" };

function settings(c: CaseInfo): string {
  const k = c.lab?.conditions;
  const mode = c.investigation_mode ? (MODE[c.investigation_mode] ?? "") : "";
  const counts = k ? `${k.rogue_requests} / ${k.investigator_requests}` : "";
  return [counts, mode].filter(Boolean).join(" · ") || c.labels.inference_label;
}

function Outcome({ c }: { c: CaseInfo }) {
  const [text, setText] = useState<{ t: string; tone: string } | null>(null);
  useEffect(() => {
    if (c.state !== "scored") return;
    let live = true;
    api
      .getCase(c.case_id)
      .then((v) => {
        const s = v.reveal?.score;
        if (!live || !s) return;
        if (s.case_kind === "benign" || v.reveal?.truth.case_kind === "benign") {
          setText(
            s.benign_false_alert
              ? { t: "False alarm", tone: "bad" }
              : { t: "Clean · nothing alleged", tone: "ok" },
          );
          return;
        }
        const obs = (s.effect_outcomes ?? []).filter((e) => e.outcome !== "unobservable");
        const caught = obs.filter((e) => e.outcome === "caught").length;
        const [n, d] = obs.length
          ? [caught, obs.length]
          : [s.step_recall?.num ?? 0, s.step_recall?.den ?? 0];
        setText({ t: `Caught ${n} / ${d}`, tone: n === d ? "ok" : "warn" });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [c.case_id, c.state]);
  const label =
    c.state === "scored"
      ? (text?.t ?? "Revealed")
      : c.state === "report_locked"
        ? "Report locked"
        : c.state === "awaiting_review"
          ? "Awaiting review"
          : humanState(c.state);
  return (
    <span className={`run-outcome ${text?.tone ?? ""}`} data-testid="run-outcome">
      {label}
    </span>
  );
}

function RunRow(p: {
  c: CaseInfo;
  current: boolean;
  open: boolean;
  onToggle: () => void;
  onOpen: (id: string) => void;
}) {
  const { c } = p;
  return (
    <li className={`run-row ${p.open ? "expanded" : ""}`} data-run={c.case_id}>
      <div className="run-line">
        <button
          className="run-main"
          aria-current={p.current ? "true" : undefined}
          // a lab run opens on Lab and replays its sandbox first (App.tsx openRecent)
          onClick={() => p.onOpen(c.case_id)}
        >
          <b>{c.title ?? c.case_id}</b>
          <span className="run-settings">{settings(c)}</span>
          <Outcome c={c} />
        </button>
        <button
          className="run-files"
          data-case={c.case_id}
          data-testid="case-files-toggle"
          aria-expanded={p.open}
          onClick={p.onToggle}
        >
          Files <span aria-hidden="true">{p.open ? "▴" : "▾"}</span>
        </button>
      </div>
      {p.open && <FileBrowser caseId={c.case_id} />}
    </li>
  );
}

/* ------------------------------------------------------------------ the Cases workspace */

export function CasesWorkspace(p: {
  cases: CaseInfo[];
  casesError: boolean;
  currentId?: string;
  onOpen: (id: string) => void;
  presets: Presets | null;
  err: string | null;
  selected: Choice | null;
  onSelect: (s: Choice) => void;
  onRun: (s: Choice) => void;
  busy: boolean;
  runtime: Runtime | null;
  mode: string | null;
  onMode: (m: string) => void;
  onDesign: () => void;
}) {
  const [filesFor, setFilesFor] = useState<string | null>(null);
  const runs = p.cases.filter((c) => c.lab);
  const others = p.cases.filter((c) => !c.lab);
  const modes = p.runtime?.capabilities?.investigation_modes;
  const is = (kind: Choice["kind"], x: string) =>
    p.selected?.kind === kind && p.selected.id === x;
  const rows = (list: CaseInfo[], testid: string) => (
    <ul className="run-list" data-testid={testid}>
      {list.map((c) => (
        <RunRow
          key={c.case_id}
          c={c}
          current={c.case_id === p.currentId}
          open={filesFor === c.case_id}
          onToggle={() => setFilesFor((v) => (v === c.case_id ? null : c.case_id))}
          onOpen={p.onOpen}
        />
      ))}
    </ul>
  );
  return (
    <div className="cases-ws">
      <section className="cases-section" aria-label="Lab runs">
        {p.casesError ? (
          <p role="status" className="amber">
            Saved runs could not be loaded.
          </p>
        ) : !runs.length ? (
          <p className="cases-empty">No lab runs yet. Run one from Lab.</p>
        ) : (
          rows(runs, "case-list")
        )}
      </section>

      <section className="cases-section" aria-label="Recordings">
        <h2>Recordings</h2>
        {p.err ? (
          <div className="banner err" role="alert">
            Could not load recordings: {p.err}. Reload to reconnect.
          </div>
        ) : !p.presets ? (
          <p role="status">Loading…</p>
        ) : !p.presets.replays.length ? (
          <p className="cases-empty">None saved.</p>
        ) : (
          <ul className="run-list recordings">
            {p.presets.replays.map((x) => (
              <li key={x.id} className="run-row">
                <div className="run-line">
                  <button
                    className={`run-main ${is("replay", x.id) ? "sel" : ""}`}
                    data-testid={`replay-${x.id}`}
                    aria-pressed={is("replay", x.id)}
                    onClick={() => p.onSelect({ kind: "replay", id: x.id })}
                  >
                    <b>{x.title}</b>
                    <span className="run-settings">
                      <span className="tag">REPLAY</span>{" "}
                      {x.inference_label ?? x.inference_mode}
                    </span>
                    <span className="run-model mono">{x.model_id}</span>
                  </button>
                  <button
                    className="run-files"
                    data-testid={
                      x.presentation_default === true
                        ? "btn-recorded-demo"
                        : `open-replay-${x.id}`
                    }
                    aria-label={`Open ${x.title}`}
                    disabled={p.busy}
                    onClick={() => p.onRun({ kind: "replay", id: x.id })}
                  >
                    Open
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <details className="cases-more" data-testid="cases-more">
        <summary>Other scenarios</summary>
        <div className="cases-more-tools">
          {(modes?.available?.length ?? 0) > 1 && (
            <label>
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
              data-testid="btn-design"
              disabled={p.busy}
              onClick={p.onDesign}
            >
              Design an environment
            </button>
          )}
        </div>
        <ul className="cases-presets">
          {(p.presets?.presets ?? []).map((x) => (
            <li key={x.id}>
              <button
                data-testid={`preset-${x.id}`}
                className={is("preset", x.id) ? "sel" : ""}
                aria-pressed={is("preset", x.id)}
                onClick={() => p.onSelect({ kind: "preset", id: x.id })}
              >
                <b>{x.title}</b>
                <small>
                  {x.difficulty} ·{" "}
                  {p.runtime?.live_inference === "CONFIGURED"
                    ? "Live AI configured"
                    : "Scripted fixture"}
                </small>
              </button>
              <button
                className="open"
                aria-label={`Open ${x.title}`}
                disabled={p.busy}
                onClick={() => p.onRun({ kind: "preset", id: x.id })}
              >
                Open
              </button>
            </li>
          ))}
        </ul>
        {!!others.length && rows(others, "other-case-list")}
      </details>
    </div>
  );
}

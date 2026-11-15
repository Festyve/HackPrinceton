import { useEffect, useRef, useState } from "react";
import { Dialog } from "./dialog";
import type { CaseInfo } from "./api";
import { humanState } from "./workbench";

const runStatus = (state: string) =>
  state === "investigating"
    ? "Investigating"
    : state === "awaiting_review"
      ? "Awaiting review"
      : state === "report_locked"
        ? "Report locked"
        : state === "scored"
          ? "Revealed"
          : humanState(state);

export type Workspace = "lab" | "cases" | "investigation" | "experiments";
const NAV: Array<[Workspace, string, string]> = [
  ["lab", "Lab", "◇"],
  ["investigation", "Investigation", "⌕"],
  ["cases", "Cases", "▤"],
  ["experiments", "Experiments", "⇄"],
];

export function Navigation({
  current,
  onNavigate,
  onHelp,
  cases = [],
  onOpen,
}: {
  current: Workspace;
  onNavigate: (w: Workspace) => void;
  state?: string;
  onHelp: () => void;
  cases?: CaseInfo[];
  onOpen?: (id: string) => void;
}) {
  const labRuns = cases.filter((c) => c.lab);
  return (
    <aside className="workspace-rail">
      <button
        className="rail-brand wordmark"
        aria-label="ALIBI Lab"
        onClick={() => onNavigate("lab")}
      >
        alibi<span className="brand-dot">.</span>
      </button>
      <nav aria-label="Main navigation">
        {NAV.map(([key, label, glyph]) => (
          <button
            key={key}
            data-testid={
              key === "investigation"
                ? "tab-case"
                : key === "experiments"
                  ? "tab-benchmark"
                  : `nav-${key}`
            }
            className={current === key ? "active" : ""}
            aria-current={current === key ? "page" : undefined}
            onClick={() => onNavigate(key)}
          >
            <span aria-hidden="true">{glyph}</span>
            {label}
          </button>
        ))}
      </nav>
      <div className="recent-runs" data-testid="recent-runs">
        <p className="rail-caption">Recent runs</p>
        {labRuns.slice(0, 4).map((c) => (
          <button key={c.case_id} onClick={() => onOpen?.(c.case_id)}>
            <span className={c.state === "scored" ? "ok" : "amber"}>●</span>
            <span>
              {c.title ?? c.case_id}
              <small>{runStatus(c.state)}</small>
            </span>
          </button>
        ))}
        {!labRuns.length && <p className="small muted">No runs yet.</p>}
      </div>
      <div className="rail-bottom">
        <button className="help-link" onClick={onHelp}>
          ⓘ <span>Help</span>
        </button>
      </div>
    </aside>
  );
}

export function ShortHelp({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="Help" onClose={onClose}>
      <ol className="short-help" data-testid="short-help">
        <li>Lab: set the balance, run the sandbox.</li>
        <li>Investigation: follow the evidence to findings.</li>
        <li>Lock the report, then reveal the result.</li>
        <li>⌘K searches cases and actions.</li>
      </ol>
    </Dialog>
  );
}

export interface PaletteAction {
  id: string;
  title: string;
  detail: string;
  action: () => void;
}
export function CommandPalette({
  actions,
  onClose,
}: {
  actions: PaletteAction[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const items = actions.filter((a) =>
    `${a.title} ${a.detail}`.toLowerCase().includes(query.toLowerCase().trim()),
  );
  useEffect(() => {
    const t = requestAnimationFrame(() => input.current?.focus());
    return () => cancelAnimationFrame(t);
  }, []);
  useEffect(() => {
    document
      .getElementById(`command-${items[selected]?.id}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selected, query]);
  const choose = (i: number) => {
    if (items[i]) {
      onClose();
      items[i].action();
    }
  };
  return (
    <Dialog title="Search cases & actions" onClose={onClose}>
      <div className="command-palette" data-testid="command-palette">
        <input
          ref={input}
          aria-label="Search cases and actions"
          placeholder="Find a case, open a view, inspect a run…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSelected(0);
          }}
          role="combobox"
          aria-expanded="true"
          aria-controls="command-results"
          aria-autocomplete="list"
          aria-activedescendant={
            items.length
              ? `command-${items[Math.min(selected, items.length - 1)].id}`
              : undefined
          }
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              setSelected((i) =>
                items.length
                  ? (i + (e.key === "ArrowDown" ? 1 : items.length - 1)) %
                    items.length
                  : 0,
              );
            }
            if (e.key === "Enter") {
              e.preventDefault();
              choose(selected);
            }
          }}
        />
        <div role="listbox" aria-label="Matching actions" id="command-results">
          {items.map((a, i) => (
            <button
              type="button"
              role="option"
              aria-selected={selected === i}
              id={`command-${a.id}`}
              key={a.id}
              className={selected === i ? "selected" : ""}
              onMouseEnter={() => setSelected(i)}
              onClick={() => choose(i)}
            >
              <span>
                <b>{a.title}</b>
                <small>{a.detail}</small>
              </span>
              <span aria-hidden="true">↵</span>
            </button>
          ))}
          {!items.length && (
            <p className="empty-command">No matching cases or actions.</p>
          )}
        </div>
        <footer>
          <span>↑ ↓ to navigate · Enter to open · Esc to close</span>
          <span>Navigation never starts a paid run.</span>
        </footer>
      </div>
    </Dialog>
  );
}

export function SavedCases({
  cases,
  onOpen,
}: {
  cases: CaseInfo[];
  onOpen: (id: string) => void;
}) {
  return (
    <section className="saved-cases">
      <div className="section-heading">
        <h2>Saved investigations</h2>
        <span className="muted small">
          {cases.length} available on this server
        </span>
      </div>
      {!cases.length ? (
        <p className="muted">
          No saved cases yet. Open a recording or create an investigation below.
        </p>
      ) : (
        <div className="saved-case-list">
          {cases.map((c) => (
            <button key={c.case_id} onClick={() => onOpen(c.case_id)}>
              <span>
                <b>{c.title ?? c.case_id}</b>
                <small>
                  {c.labels.inference_label} ·{" "}
                  {c.scored === false
                    ? "Unscored import"
                    : c.labels.evidence_origin}
                </small>
                {c.labels.worker_choices && (
                  <small>{c.labels.worker_choices}</small>
                )}
                {c.labels.changed_objective_policy && (
                  <small>{c.labels.changed_objective_policy}</small>
                )}
              </span>
              <span className="case-list-status">
                {humanState(c.state)}
                <span aria-hidden="true"> ↗</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

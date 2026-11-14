import { useEffect, useRef, useState } from "react";
import { Dialog } from "./dialog";
import type { CaseInfo } from "./api";
import { humanState } from "./workbench";

export type Workspace = "lab" | "cases" | "investigation" | "experiments";
const NAV: Array<[Workspace, string, string]> = [
  ["lab", "Lab", "◇"],
  ["cases", "Cases", "▤"],
  ["investigation", "Investigation", "⌕"],
  ["experiments", "Experiments", "⇄"],
];

export function Pip({ state = "ready" }: { state?: string }) {
  const pose =
    state === "scored"
      ? "finished"
      : state === "awaiting_review"
        ? "waiting for review"
        : state === "investigating"
          ? "inspecting"
          : "ready";
  return (
    <svg
      className={`pip pip-${pose.split(" ")[0]}`}
      viewBox="0 0 64 64"
      role="img"
      aria-label={`Pip, ${pose}`}
    >
      <g aria-hidden="true">
        <path d="M17 44c-5 1-9 7-9 12h35c0-9-5-13-11-14" fill="#70796f" />
        <path
          d="M18 24c-5 4-4 17 0 21 5 6 18 5 23-2 3-5 5-15-1-20"
          fill="#dcc4a0"
        />
        <path d="M12 27c1-8 5-14 16-14 10 0 17 5 17 14z" fill="#d9ae73" />
        <path
          d="M11 27h37"
          fill="none"
          stroke="#eacb9d"
          strokeWidth="4"
          strokeLinecap="round"
        />
        <circle cx="25" cy="34" r="2" fill="#27302e" />
        <circle cx="36" cy="34" r="2" fill="#27302e" />
        <path
          d={pose === "finished" ? "M26 42q5 4 9-1" : "M28 42h5"}
          fill="none"
          stroke="#574c3d"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle
          cx="44"
          cy="41"
          r="10"
          fill="#27383c"
          fillOpacity=".8"
          stroke="#e2b978"
          strokeWidth="3"
        />
        <path
          d="m51 49 8 9"
          stroke="#e2b978"
          strokeWidth="5"
          strokeLinecap="round"
        />
        <path
          d="m40 37 4-2"
          stroke="#dce6df"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </g>
    </svg>
  );
}

export function Navigation({
  current,
  onNavigate,
  state,
  onHelp,
}: {
  current: Workspace;
  onNavigate: (w: Workspace) => void;
  state?: string;
  onHelp: () => void;
}) {
  return (
    <aside className="workspace-rail">
      <p className="rail-caption">Workspace</p>
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
      <div className="rail-bottom">
        <div className="pip-note">
          <Pip state={state} />
          <div>
            <b>Pip</b>
            <small>
              {state === "awaiting_review"
                ? "Your review is needed"
                : state === "investigating"
                  ? "Following the evidence"
                  : state === "scored"
                    ? "Evidence, then answers"
                    : "A little curiosity helps"}
            </small>
          </div>
        </div>
        <button className="help-link" onClick={onHelp}>
          How the lab works <span aria-hidden="true">↗</span>
        </button>
        <p className="rail-footnote">
          A controlled research environment.
          <br />
          Every conclusion needs a source.
        </p>
      </div>
    </aside>
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

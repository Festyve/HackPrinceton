import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { RawTarget } from "./App";

export const EvidenceCtx = createContext<(t: string | RawTarget) => void>(() => undefined);

export function Chip({ id }: { id: string }) {
  const open = useContext(EvidenceCtx);
  return (
    <button className="chip" data-testid={`chip-${id}`} onClick={() => open(id)} title={`Open raw record for ${id}`}>
      {"\u2315 "}{id.replace(/^ev_/, "")}
    </button>
  );
}
export function Chips({ ids }: { ids?: string[] }) {
  if (!ids || !ids.length) return null;
  return <span className="chips">{ids.map((i, k) => <Chip key={i + k} id={i} />)}</span>;
}
export function Section(p: { title: string; children: ReactNode; note?: string }) {
  return (
    <section className="sec">
      <h3>{p.title}{p.note && <small>{p.note}</small>}</h3>
      {p.children}
    </section>
  );
}
export const fmtTime = (s?: string | null): string => (s ? s.replace("T", " ").replace(/(\+00:00|Z)$/, "Z").slice(0, 20) : "");
export const hhmmss = (s?: string | null): string => {
  const m = s ? /T(\d\d:\d\d:\d\d)/.exec(s) : null;
  return m ? m[1] : s ?? "";
};
export function ratio(r?: { num?: number | null; den?: number | null; value?: number | null; na_reason?: string | null } | null): string {
  if (!r) return "\u2014";
  const frac = r.num == null || r.den == null ? "" : `${r.num}/${r.den}`;
  if (r.value == null) return `${frac ? frac + " " : ""}N/A${r.na_reason ? " (" + r.na_reason + ")" : ""}`;
  return `${frac} (${Math.round(r.value * 100)}%)`;
}

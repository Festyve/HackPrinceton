import type { AttributionAssessment, Finding, ServerEvent, Usage } from "./api";

export interface TodoItem { text: string; status: string }
export interface AgentInfo { agent: string; status: string; task?: string; summary?: string }
export interface ToolInfo { seq: number; agent: string; tool: string; args?: unknown; result_summary?: string; evidence_ids: string[]; ok: boolean; ms?: number }
export interface Stage { name: string; status: string; info: Record<string, unknown> }
export interface Run {
  lastSeq: number;
  stages: Record<string, Stage>;
  todo: TodoItem[];
  agents: Record<string, AgentInfo>;
  agentOrder: string[];
  tools: ToolInfo[];
  findings: Record<string, { finding: Finding; phase: string }>;
  findingOrder: string[];
  notes: Array<{ path: string; preview: string }>;
  attribution: AttributionAssessment | null;
  usage: Usage | null;
  error: string | null;
  gone: boolean;
}
export const emptyRun = (): Run => ({
  lastSeq: 0, stages: {}, todo: [], agents: {}, agentOrder: [], tools: [], findings: {}, findingOrder: [],
  notes: [], attribution: null, usage: null, error: null, gone: false,
});

type D = Record<string, unknown>;
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const arr = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** Pure reducer: apply one streamed event. Events at or below lastSeq are ignored (dedupe after reconnect). */
export function applyEvents(run: Run, events: ServerEvent[]): Run {
  let r = run;
  for (const ev of events) {
    if (ev.seq <= r.lastSeq) continue;
    r = { ...r, lastSeq: ev.seq };
    const d = ev.data as D;
    switch (ev.type) {
      case "stage": {
        const name = str(d.name);
        const prev = r.stages[name];
        r = { ...r, stages: { ...r.stages, [name]: { name, status: str(d.status), info: { ...(prev?.info ?? {}), ...((d.info as D) ?? {}) } } } };
        break;
      }
      case "todo":
        r = { ...r, todo: Array.isArray(d.items) ? (d.items as TodoItem[]) : r.todo };
        break;
      case "agent": {
        const a = str(d.agent);
        const prev = r.agents[a];
        r = {
          ...r,
          agents: { ...r.agents, [a]: { ...prev, agent: a, status: str(d.status), task: str(d.task) || prev?.task, summary: str(d.summary) || prev?.summary } },
          agentOrder: r.agentOrder.includes(a) ? r.agentOrder : [...r.agentOrder, a],
        };
        break;
      }
      case "tool":
        r = {
          ...r,
          tools: [...r.tools, {
            seq: ev.seq, agent: str(d.agent), tool: str(d.tool), args: d.args, result_summary: str(d.result_summary),
            evidence_ids: arr(d.evidence_ids), ok: d.ok !== false, ms: typeof d.ms === "number" ? d.ms : undefined,
          }],
        };
        break;
      case "finding": {
        const f = d.finding as Finding | undefined;
        if (f && f.id) {
          r = {
            ...r,
            findings: { ...r.findings, [f.id]: { finding: f, phase: str(d.phase) } },
            findingOrder: r.findingOrder.includes(f.id) ? r.findingOrder : [...r.findingOrder, f.id],
          };
        }
        break;
      }
      case "note":
        r = { ...r, notes: [...r.notes, { path: str(d.path), preview: str(d.preview) }] };
        break;
      case "attribution":
        r = { ...r, attribution: (d.attribution as AttributionAssessment) ?? r.attribution };
        break;
      case "usage":
        r = { ...r, usage: (d.usage as Usage) ?? r.usage };
        break;
      case "error":
        r = { ...r, error: str(d.message) || "error" };
        break;
      case "gone":
        r = { ...r, gone: true };
        break;
      default:
        break;
    }
  }
  return r;
}

export const CLAIM_TITLES: Record<string, string> = {
  local_log_removal: "Host log line removed",
  policy_violating_transfer: "Transfer to a non‑approved destination",
  data_staging: "Data staged before transfer",
  retention_explained_absence: "Gap explained by log rotation",
  policy_consistent_transfer: "Transfer consistent with policy",
  collection_gap: "Collection gap (cause unknown)",
  account_use: "Account use",
  other: "Other observation",
};
export const CATEGORY_WORDS: Record<string, string> = {
  incident_allegation: "incident allegation",
  benign_explanation: "benign explanation",
  unresolved: "unresolved",
  neutral_reconstruction: "neutral reconstruction",
};
export const VERIFICATION_WORDS: Record<string, string> = {
  supported_observation: "Supported by a deterministic check",
  invalid_reference: "Rejected: cites evidence that does not exist",
  unresolved_interpretation: "Not supported",
  structurally_valid: "References valid",
  not_checked: "Not checked",
};
export const CATEGORY_ORDER = ["incident_allegation", "neutral_reconstruction", "benign_explanation", "unresolved"];

export const STATE_ORDER = ["created", "generating", "frozen", "investigating", "awaiting_review", "report_locked", "scored"];
export const stateIdx = (s: string): number => STATE_ORDER.indexOf(s);
export const hasReport = (s: string): boolean => stateIdx(s) >= stateIdx("awaiting_review");
export const short = (h: unknown, n = 12): string => (typeof h === "string" ? h.slice(0, n) : "");

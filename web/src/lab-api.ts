import { req } from "./api";
import type { CaseInfo, Usage } from "./api";

export interface LabConditions {
  preset: string | null;
  preset_label: string;
  rogue_requests: number;
  investigator_requests: number;
  rogue_permissions: string;
  context_load: string;
  allowance_enforced?: boolean;
}
export interface LabLineage {
  root_case_id: string;
  parent_case_id: string | null;
  comparison: "investigator_budget" | "rogue_permissions" | null;
  changed: Record<string, { from: unknown; to: unknown }> | null;
  note?: string;
  same_evidence_as_parent?: boolean;
}
export interface LabMeta {
  version: string;
  config: {
    workers: Array<{ id: string; account: string; job: string; goal: string }>;
    ticks: number;
    tick_seconds: number;
  };
  conditions: LabConditions;
  provenance: {
    ordinary_work_label: string;
    changed_objective_label: string;
    worker_usage?: Usage | null;
  };
  lineage: LabLineage;
}
export interface LabOptions {
  version: string;
  variants: Array<{ id: string; label: string }>;
  presets: Array<{
    id: string;
    label: string;
    rogue_requests: number;
    investigator_requests: number;
  }>;
  preset_note: string;
  rogue_permissions: Array<{ id: string; actions: string[] }>;
  context_load: Array<{ id: string; unrelated_records_per_tick: number }>;
  ordinary_work: Array<{ id: string; label: string; available: boolean }>;
  defaults: {
    variant: string;
    preset: string;
    rogue_permissions: string;
    context_load: string;
    ordinary_work: string;
  };
  changed_objective_policy: string;
}
export interface LabView extends LabMeta {
  case_id: string;
  state: string;
  activity: Array<{
    event_id: string;
    worker: string;
    account: string;
    t: string;
    action: string;
    dataset: string | null;
    status: string | null;
  }>;
  activity_total: number;
  activity_source: string;
  scheduler_records: Array<{ event_id: string; t: string; text: string }>;
  operator_record: { available: boolean; note: string };
}
export interface OperatorRecord {
  label: string;
  transition: { worker: string; tick: number; t: string } | null;
  records: Array<{
    seq: number;
    tick: number;
    t: string;
    worker: string;
    account: string;
    objective: string;
    action: string;
    target: string | null;
    status: string;
    outcome: string;
    artifacts: string[];
  }>;
}
export interface LabRuns {
  root_case_id: string;
  note: string;
  runs: Array<{
    case_id: string;
    bundle_id: string;
    state: string;
    outcome: string;
    error: string | null;
    stop_reason: string | null;
    conditions: LabConditions;
    lineage: LabLineage;
    labels: CaseInfo["labels"];
    allowed: { investigator_requests: number; rogue_requests: number };
    used: Pick<
      Usage,
      | "llm_calls"
      | "tokens_in"
      | "tokens_out"
      | "cost_estimate_usd"
      | "wall_seconds"
    > | null;
    findings: { total: number; incident_allegations_accepted: number } | null;
    scored: {
      effects_established: { num: number; den: number; value: number | null };
      benign_false_alert: boolean | null;
    } | null;
  }>;
}
export interface StageEvent {
  t: string | null;
  line_t?: string | null;
  worker: string;
  account: string;
  action: string;
  dataset: string | null;
  station: string;
  kind: "routine" | "unassigned" | "local_record_missing";
  reason: string | null;
  evidence_id: string;
  kept_by_collector: boolean;
  missing_from_local_log: boolean;
}
export interface StageView {
  label: string;
  workers: Array<{ id: string; account: string; job: string }>;
  stations: Array<{ id: string; label: string; path: string }>;
  events: StageEvent[];
  summary: {
    routine: number;
    unassigned: number;
    local_records_missing: number;
    collector_records: number;
    workers_with_unassigned_activity: string[];
    copies_out?: number;
  };
}
export interface TraceSpan {
  span_id: string;
  parent_id: string | null;
  kind: "run" | "delegation" | "tool";
  actor: string;
  tool?: string;
  task?: string;
  status: string;
}
export interface TraceView {
  spans: TraceSpan[];
}
/** One step of the investigator's walk on the stage, built only from recorded tool spans. */
export interface InvestigatorStep {
  station: "log" | "tmp" | "sched" | "center";
  caption: string;
  delegate: string | null;
  collector: boolean;
}
const LEADS = new Set(["lead-investigator", "single-agent"]);
const pretty = (s: string) => s.replace(/[-_]/g, " ");
export function investigatorSteps(trace: TraceView): InvestigatorStep[] {
  const steps: Array<InvestigatorStep & { key: string; n: number }> = [];
  for (const s of trace.spans) {
    if (s.kind !== "tool" || !s.tool) continue;
    const t = s.tool.toLowerCase();
    const delegate = LEADS.has(s.actor) ? null : s.actor;
    let station: InvestigatorStep["station"] = "center";
    let caption = pretty(s.tool);
    let collector = false;
    if (/local.*collector|reconcil|access_log|log_gap/.test(t)) {
      station = "log";
      collector = true;
      caption = "Comparing local log with collector copy";
    } else if (/transfer|flow|export|session|egress/.test(t)) {
      station = "tmp";
      caption = "Checking transfers out of tmp exports";
    } else if (/assign|schedul/.test(t)) {
      station = "sched";
      caption = "Checking who was assigned what";
    } else if (/submit_finding/.test(t)) caption = "Filing a finding";
    else if (/brief/.test(t)) caption = "Reading the case brief";
    const key = `${s.actor}|${station}|${caption}`;
    const last = steps[steps.length - 1];
    if (last && last.key === key) {
      last.n += 1;
      continue;
    }
    steps.push({ station, caption, delegate, collector, key, n: 1 });
  }
  return steps.map((st) => ({
    station: st.station,
    delegate: st.delegate,
    collector: st.collector,
    caption:
      (st.delegate ? `${pretty(st.delegate)}: ` : "") +
      (st.n > 1 && st.caption === "Filing a finding"
        ? `Filing ${st.n} findings`
        : st.caption + (st.n > 1 ? ` (×${st.n})` : "")),
  }));
}
const q = encodeURIComponent;
const post = <T>(path: string, body: unknown) =>
  req<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
export const labApi = {
  options: () => req<LabOptions>("/api/lab/options"),
  create: (body: Record<string, unknown>) =>
    post<{ case: CaseInfo; lab: LabView }>("/api/lab/experiments", body),
  view: (id: string) => req<LabView>(`/api/cases/${q(id)}/lab`),
  stage: (id: string) => req<StageView>(`/api/cases/${q(id)}/lab/stage`),
  trace: (id: string) => req<TraceView>(`/api/cases/${q(id)}/trace`),
  operator: (id: string) =>
    req<OperatorRecord>(`/api/cases/${q(id)}/lab/operator`),
  comparisons: (id: string) =>
    req<LabRuns>(`/api/cases/${q(id)}/lab/comparisons`),
  compare: (id: string, body: Record<string, unknown>) =>
    post<{ case: CaseInfo; lab: LabView }>(
      `/api/cases/${q(id)}/lab/comparisons`,
      body,
    ),
};
export const permissionLabel = (id: string) =>
  ({
    export_only: "Synthetic export only",
    export_log: "Export + own local-log edits",
    export_log_artifact: "Export + bounded local-artifact edits",
  })[id] ?? id.replace(/_/g, " ");

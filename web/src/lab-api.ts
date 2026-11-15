import { req } from "./api";
import type { CaseInfo, Usage } from "./api";

export interface LabConditions {
  preset: string | null;
  preset_label: string;
  rogue_requests: number;
  investigator_requests: number;
  rogue_permissions: string;
  context_load: string;
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
  };
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

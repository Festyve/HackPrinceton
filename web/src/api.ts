import type {
  AttributionAssessment,
  EvidenceManifest,
  Finding,
  InvestigationReport,
  QuestionAnswer,
  QuestionClaim,
  Score,
  Usage,
} from "./generated/contracts";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface Capabilities {
  investigation_modes?: {
    available?: string[];
    labels?: Record<string, string>;
    default?: string;
  };
  questions?: {
    endpoint?: boolean;
    model_answers?: "CONFIGURED" | "BLOCKED";
    max_question_chars?: number;
  };
  source_experiments?: { endpoint?: boolean; max_excluded_sources?: number };
  report_export?: { endpoint?: boolean };
  sensor_streams?: { endpoint?: boolean };
}
export interface Runtime {
  runtime_mode?: string;
  live_inference?: "BLOCKED" | "CONFIGURED";
  live_block_reason?: string | null;
  capabilities?: Capabilities;
}
export interface Preset {
  id: string;
  title: string;
  difficulty: string;
  card_id: string;
  seed: number;
  blurb: string;
}
export interface Replay {
  id: string;
  title: string;
  inference_mode?: string;
  inference_label?: string;
  model_id?: string | null;
  recorded_at?: string | null;
  note?: string;
}
export interface Presets {
  presets: Preset[];
  replays: Replay[];
}

export interface CaseInfo {
  case_id: string;
  state: string;
  detail?: string;
  title?: string;
  difficulty?: string;
  seed?: number;
  preset_id?: string;
  runner_id?: string;
  error?: string | null;
  review_decision?: string | null;
  timings?: { generate_s?: number | null; investigate_s?: number | null };
  card_id?: string;
  scored?: boolean;
  investigation_mode?: string | null;
  parent_case_id?: string | null;
  excluded_sources?: ExcludedSource[];
  labels: {
    evidence_origin: string;
    inference: string;
    inference_label: string;
    playback: string;
    model_id?: string | null;
    investigation_mode_label?: string;
  };
}
export interface ExcludedSource {
  source_id: string;
  source: string;
  host: string;
  artifact: string;
  lines?: number;
  tamper_exposure?: string;
}
/** One claim of the original report, re-checked by the server against the reduced evidence. */
export interface ExperimentClaim {
  finding_id: string;
  claim_type: string;
  category?: string;
  host?: string;
  object_or_session?: string;
  change: "retains_support" | "loses_support" | "never_supported";
  reason?: string;
  evidence_ids_remaining?: string[];
}
export interface SourceExperiment {
  role: "original" | "derived";
  case_id: string;
  parent_case_id?: string;
  excluded_sources?: ExcludedSource[];
  sources_remaining?: number;
  events_remaining?: number;
  events_original?: number;
  children?: Array<{
    child_case_id: string;
    title?: string;
    state?: string;
    excluded_sources?: ExcludedSource[];
  }>;
  comparison?: {
    method?: string;
    claims?: ExperimentClaim[];
    attribution?: {
      change?: string;
      child_statement?: string;
      note?: string;
    } | null;
    summary?: {
      retains_support?: number;
      loses_support?: number;
      never_supported?: number;
      claims_total?: number;
      reading?: string;
    };
    coverage?: { child?: { limits?: string[] } };
  } | null;
}
export interface SourceExperimentCreated {
  child_case_id: string;
  parent_case_id: string;
  excluded_sources?: ExcludedSource[];
}
export interface Spend {
  configured: boolean;
  readable?: boolean;
  cap_usd?: number;
  limit_in_force_usd?: number;
  spent_usd?: number;
  unreconciled_usd?: number;
  reserved_usd?: number;
  calls?: number;
  note?: string;
}
export interface SensorPoint {
  event_id: string;
  ts: string;
  temp_c: number;
  seq?: number | null;
}
export interface SensorSeries {
  key: "stored" | "reference";
  source: string;
  label: string;
  present: boolean;
  host?: string | null;
  tamper_exposure?: string | null;
  total_points: number;
  truncated?: boolean;
  points: SensorPoint[];
}
export interface SensorDiscrepancy {
  discrepancy_id: string;
  start: string;
  end: string;
  reference_range_c: [number, number];
  local_range_c: [number, number];
  max_difference_c: number;
  classification: "unexplained" | "explained_maintenance" | "isolated_reading";
  maintenance_id?: string | null;
  reference_event_ids: string[];
  local_event_ids: string[];
}
export interface SensorStreams {
  applicable: boolean;
  status: string;
  status_reason?: string | null;
  sensor?: string;
  permitted_range_c?: [number, number];
  maintenance_windows?: Array<{
    id?: string | null;
    start?: string;
    end?: string;
    note?: string;
  }>;
  series: SensorSeries[];
  discrepancies?: SensorDiscrepancy[];
  excursions?: Array<{
    excursion_id: string;
    start: string;
    end: string;
    peak_c: number;
    local_agrees: boolean;
    reference_event_ids: string[];
  }>;
  coverage_limits?: string[];
  limits?: string[];
  produced_by?: string;
}
export interface TruthStep {
  step_id: string;
  step_name: string;
  attack_id?: string | null;
  attack_label?: string;
  host?: string;
  account_used?: string | null;
  t_start?: string;
  t_end?: string;
  execution_status: string;
  outcome?: string;
  operator_true?: string | null;
}
export interface Truth {
  case_kind: string;
  variant?: string;
  difficulty?: string;
  seed?: number;
  plan_source?: string;
  plan_label?: string;
  steps?: TruthStep[];
  effects?: Array<{
    effect_id: string;
    effect_type: string;
    host: string;
    object: string;
    observable?: boolean;
  }>;
  benign_outcomes?: Array<{
    kind: string;
    host?: string;
    actor_account?: string | null;
    t_start?: string;
    t_end?: string;
    description?: string;
  }>;
  attribution?: {
    account_used?: string | null;
    account_owner_person?: string | null;
    operator_true?: string | null;
    framed?: boolean | null;
    session?: string | null;
  } | null;
}
export interface SourceInfoLite {
  artifact: string;
  host: string;
  source: string;
  logical_file?: string | null;
  tamper_exposure: "host_local_writable" | "independent_witness";
}
export interface CaseView {
  case: CaseInfo;
  card?: { id: string; title: string; tip: string; audience_setup: string };
  manifest?: EvidenceManifest;
  report: InvestigationReport | null;
  reveal: null | { score: Score; truth: Truth };
  last_seq?: number;
}
export interface ServerEvent {
  seq: number;
  ts: string;
  type: string;
  data: Record<string, unknown>;
}

export interface EvEvent {
  id: string;
  ts: string;
  host: string;
  source: string;
  actor?: string | null;
  action: string;
  object?: string | null;
  raw: string;
  artifact?: string;
  line?: number;
  byte_offset?: number;
}
export interface RawView {
  artifact: string;
  host: string;
  source: string;
  sha256: string;
  tamper_exposure: "host_local_writable" | "independent_witness";
  total_lines: number;
  focus_line: number;
  coverage_note?: string;
  lines: Array<{ n: number; text: string; focus: boolean }>;
}
export interface CompareRow {
  ts: string;
  text: string;
  status: string;
  reason?: string | null;
  actor?: string | null;
  action?: string | null;
  session_id?: string | null;
  focus?: boolean;
  local: { event_id: string; artifact: string; line: number } | null;
  collector: {
    event_id: string;
    seq?: number;
    received?: string;
    artifact: string;
    line: number;
  } | null;
}
export interface Compare {
  host: string;
  file: string;
  status: string;
  status_reason?: string | null;
  rows_total?: number;
  counts: Record<string, number>;
  local_coverage_start?: string | null;
  coverage_basis?: string | null;
  rotations?: unknown[];
  legend?: Record<string, string>;
  rows: CompareRow[];
}
export interface Gap {
  kind: string;
  start: string;
  end: string;
  label: string;
  evidence_ids: string[];
}
export interface Lane {
  key: string;
  label: string;
  independent_witness: boolean;
  counts: number[];
  total: number;
  gaps: Gap[];
  marks: Array<{ event_id: string; ts: string; finding_ids: string[] }>;
}
export interface Timeline {
  start: string;
  end: string;
  bucket_minutes: number;
  buckets: number;
  lanes: Lane[];
}
export interface Explanation {
  key: string;
  question: string;
  answer: string;
  evidence_ids: string[];
  available: boolean;
  label: string;
}

export interface Ratio {
  num?: number | null;
  den?: number | null;
  value?: number | null;
  na_reason?: string | null;
}
export interface BenchSystem {
  id: string;
  label?: string;
  inference?: string;
  status?: string;
  status_detail?: string | null;
  model_id?: string | null;
  n_cases?: number;
  completed?: number;
  errors?: number;
  aggregate?: null | {
    step_recall?: Ratio | null;
    proposal_precision?: Ratio | null;
    final_precision?: Ratio | null;
    coverup_detected?: Ratio | null;
    account_identification?: Ratio | null;
    benign_false_alert?: Ratio | null;
    benign_raw_alert?: Ratio | null;
    raw_incident_proposals?: number | null;
    false_claims_final?: number | null;
    unsupported_named_attribution?: number | null;
    abstained?: Ratio | null;
    evidence_reference_validity?: Ratio | null;
    median_wall_seconds?: number | null;
    llm_calls?: number | null;
    tokens_in?: number | null;
    tokens_out?: number | null;
  };
}
export interface PairedSummary {
  suites: Array<{ suite: string; run_id: string; cases: number }>;
  systems: Array<{
    id: string;
    label: string;
    cells: number;
    censored: number;
    aggregate: null | {
      step_recall?: Ratio | null;
      coverup_detected?: Ratio | null;
      benign_false_alert?: Ratio | null;
      false_claims_final?: number | null;
      unsupported_named_attribution?: number | null;
      cost_estimate_usd?: number | null;
    };
  }>;
  note?: string;
  model?: string | null;
  inference?: string | null;
  incident_cases?: number;
  benign_cases?: number;
  verifier_feedback_during_investigation?: boolean;
  correct_findings_not_counted?: Array<{
    suite: string;
    case_ref: string;
    system_id: string;
    claim_type: string;
    status: string;
    check_result: string;
  }>;
}
export interface Benchmark {
  available: boolean;
  paired_summary?: PairedSummary | null;
  reason?: string;
  suite?: string;
  generated_at?: string;
  git_commit?: string;
  scorer_version?: string;
  evidence_origin?: string;
  cases?: Array<{
    case_ref: string;
    kind?: string;
    group?: string;
    variant?: string;
    seed?: number;
    scorable_effects?: number;
    events?: number;
  }>;
  systems?: BenchSystem[];
  runs?: Array<{
    system_id: string;
    case_ref: string;
    status?: string;
    score?: Score | null;
  }>;
  notes?: string[];
  reproduce?: string[];
  ai_pilot?: {
    suite?: string;
    run_id?: string;
    generated_at?: string;
    git_commit?: string;
    system_runs_started?: number;
    model_settings?: {
      lead_model?: string;
      effort?: string;
      human_review?: string;
      refusal_fallback?: string;
    } | null;
  } | null;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiError(0, "Cannot reach the ALIBI server: " + String(e));
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) {
    const b = (body ?? {}) as {
      error?: unknown;
      detail?: unknown;
      state?: unknown;
    };
    const msg =
      typeof b.error === "string"
        ? b.error
        : typeof b.detail === "string"
          ? b.detail
          : `HTTP ${res.status}`;
    throw new ApiError(
      res.status,
      b.state ? `${msg} (state: ${String(b.state)})` : msg,
    );
  }
  return body as T;
}
const post = <T>(path: string, body: unknown = {}) =>
  req<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

export const token = (): string =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : String(Math.random()).slice(2) + Date.now();

const q = encodeURIComponent;
export const api = {
  runtime: () => req<Runtime>("/api/runtime"),
  presets: () => req<Presets>("/api/presets"),
  createCase: (preset_id: string, investigation_mode?: string | null) =>
    post<CaseView>("/api/cases", {
      preset_id,
      client_token: token(),
      ...(investigation_mode ? { investigation_mode } : {}),
    }),
  openReplay: (id: string) =>
    post<CaseView>(`/api/replays/${q(id)}/open`, { client_token: token() }),
  getCase: (id: string) => req<CaseView>(`/api/cases/${q(id)}`),
  eventsJson: (id: string, after: number) =>
    req<{ events: ServerEvent[]; state: string }>(
      `/api/cases/${q(id)}/events.json?after=${after}`,
    ),
  review: (id: string, decision: "accept" | "reject") =>
    post<CaseView>(`/api/cases/${q(id)}/review`, { decision }),
  reveal: (id: string) => post<CaseView>(`/api/cases/${q(id)}/reveal`),
  reset: (id: string) => post<unknown>(`/api/cases/${q(id)}/reset`),
  evEvents: (id: string, ids: string) =>
    req<{ events: EvEvent[]; missing: string[] }>(
      `/api/cases/${q(id)}/evidence/events?ids=${q(ids)}`,
    ),
  raw: (id: string, artifact: string, line: number) =>
    req<RawView>(
      `/api/cases/${q(id)}/evidence/raw?artifact=${q(artifact)}&line=${line}&radius=6`,
    ),
  compare: (id: string, host: string, file: string) =>
    req<Compare>(
      `/api/cases/${q(id)}/evidence/compare?host=${q(host)}&file=${q(file)}&radius=5`,
    ),
  timeline: (id: string) =>
    req<Timeline>(`/api/cases/${q(id)}/evidence/timeline`),
  explanations: (id: string) =>
    req<{ explanations: Explanation[] }>(`/api/cases/${q(id)}/explanations`),
  benchmark: () => req<Benchmark>("/api/benchmark"),
  questions: (id: string) =>
    req<{ questions: QuestionAnswer[] }>(`/api/cases/${q(id)}/questions`),
  ask: (id: string, question: string, client_token: string) =>
    post<QuestionAnswer>(`/api/cases/${q(id)}/questions?wait_s=20`, {
      question,
      client_token,
    }),
  question: (id: string, questionId: string) =>
    req<QuestionAnswer>(`/api/cases/${q(id)}/questions/${q(questionId)}`),
  sourceExperiment: (id: string) =>
    req<SourceExperiment>(`/api/cases/${q(id)}/source-experiment`),
  createSourceExperiment: (
    id: string,
    excluded_source_ids: string[],
    client_token: string,
  ) =>
    // The reduced view is examined by the deterministic checks: no model is called and nothing is spent.
    post<SourceExperimentCreated>(`/api/cases/${q(id)}/source-experiments`, {
      excluded_source_ids,
      client_token,
      runner: "deterministic",
      autostart: true,
    }),
  spend: () => req<Spend>("/api/spend"),
  sensorStreams: (id: string) =>
    req<SensorStreams>(`/api/cases/${q(id)}/evidence/sensor-streams`),
  reportExportUrl: (id: string) =>
    `/api/cases/${q(id)}/report-export?format=markdown`,
};

export type {
  AttributionAssessment,
  Finding,
  Usage,
  Score,
  QuestionAnswer,
  QuestionClaim,
};

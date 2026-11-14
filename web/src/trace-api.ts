import { useEffect, useState } from "react";
import { req } from "./api";
import type { TodoItem } from "./model";

export interface TraceSpan {
  span_id: string;
  parent_id: string | null;
  kind: string;
  actor: string;
  tool?: string;
  task?: string;
  arguments?: unknown;
  result_summary?: string;
  evidence_ids?: string[];
  status: string;
  start_seq: number;
  end_seq?: number;
  start: string;
  end?: string;
  ms?: number;
}
export interface RecordedTrace {
  note: string;
  spans: TraceSpan[];
  plan: Array<{
    seq: number;
    t: string;
    items: TodoItem[];
    added: string[];
    removed: string[];
    after: { seq: number; what: string; summary: string } | null;
  }>;
  case_file: Array<{
    seq: number;
    t: string;
    op: string;
    path: string;
    preview?: string;
  }>;
  behaviors: {
    planned_before_examining: boolean;
    plan_revisions: Array<{
      seq: number;
      added: string[];
      removed: string[];
      after: { seq: number; what: string; summary: string } | null;
    }>;
    case_file: { writes: number; reads_after_a_write: number; paths: string[] };
    resumed: { times: number; tool_calls_after_resume: number };
  };
}
/** The server computes nesting and behavior from recorded events, never from model thoughts. */
export function useRecordedTrace(caseId: string, lastSeq: number) {
  const [trace, setTrace] = useState<RecordedTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    req<RecordedTrace>(`/api/cases/${encodeURIComponent(caseId)}/trace`)
      .then((t) => {
        if (live) {
          setTrace(t);
          setError(null);
        }
      })
      .catch(
        (e) => live && setError(e instanceof Error ? e.message : String(e)),
      );
    return () => {
      live = false;
    };
  }, [caseId, lastSeq]);
  return { trace, error };
}

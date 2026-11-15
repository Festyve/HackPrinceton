import { req } from "./api";
import type { LabRuns } from "./lab-api";

export interface CaseFileEntry {
  path: string;
  kind: "markdown" | "json" | "text";
  title: string;
  available: boolean;
  reason: string | null;
}
export interface CaseFileListing {
  case_id: string;
  title: string | null;
  state: string;
  note: string;
  files: CaseFileEntry[];
}
export interface CaseFileContent extends CaseFileEntry {
  case_id: string;
  content: string;
}
/** The comparisons table as the server sends it, with the fields the older type does not name. */
export type ExperimentRun = LabRuns["runs"][number] & {
  is_root?: boolean;
  scored:
    | (NonNullable<LabRuns["runs"][number]["scored"]> & {
        case_kind?: string | null;
      })
    | null;
};
export interface ExperimentRuns extends Omit<LabRuns, "runs"> {
  runs: ExperimentRun[];
  scores_withheld?: boolean;
}
const q = encodeURIComponent;
export const filesApi = {
  list: (id: string) => req<CaseFileListing>(`/api/cases/${q(id)}/files`),
  content: (id: string, path: string) =>
    req<CaseFileContent>(`/api/cases/${q(id)}/files/content?path=${q(path)}`),
  experiment: (id: string) =>
    req<ExperimentRuns>(`/api/cases/${q(id)}/lab/comparisons`),
};

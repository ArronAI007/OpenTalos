export interface ResearchState {
  topic: string;
  findings: string[];
  draft: string;
  approved: boolean;
  nextAgent: "researcher" | "writer" | "DONE";
}

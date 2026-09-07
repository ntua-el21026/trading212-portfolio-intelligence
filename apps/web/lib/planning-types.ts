import type { TargetNode } from "@trading212/api-contracts";

export interface PlanningTargetOption {
  id: string;
  key: string;
  holding_id: string | null;
  node: TargetNode;
}

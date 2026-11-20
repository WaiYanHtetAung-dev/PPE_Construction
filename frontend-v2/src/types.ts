export type PageId =
  | "overview"
  | "live"
  | "cameras"
  | "incidents"
  | "reports"
  | "models"
  | "settings";

export type Severity = "critical" | "high" | "medium" | "low";
export type CameraStatus = "online" | "offline" | "maintenance";

export interface Camera {
  id: string;
  name: string;
  zone: string;
  status: CameraStatus;
  fps: number;
  resolution: string;
  image: string;
  lastSeen: string;
  detections: number;
}

export interface Incident {
  id: string;
  type: string;
  camera: string;
  zone: string;
  occurredAt: string;
  severity: Severity;
  status: "Open" | "Reviewing" | "Resolved";
  confidence: number;
  assignee: string;
}

export interface Metric {
  label: string;
  value: string;
  change: string;
  direction: "up" | "down" | "neutral";
  icon: string;
  tone: "blue" | "green" | "orange" | "red";
}

export interface ModelVersion {
  version: string;
  status: "Deployed" | "Ready" | "Training";
  precision: number;
  recall: number;
  map: number;
  createdAt: string;
  dataset: string;
}

export interface DashboardSnapshot {
  metrics: Metric[];
  cameras: Camera[];
  incidents: Incident[];
  weeklyCompliance: number[];
  siteCompliance: { label: string; value: number; color: string }[];
}

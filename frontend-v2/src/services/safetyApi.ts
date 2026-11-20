import { cameras, dashboard, incidents, modelVersions } from "../data/mockData";
import type { Camera, DashboardSnapshot, Incident, ModelVersion } from "../types";

/**
 * UI-facing data contract. Replace MockSafetyApi with an adapter around an
 * OpenAPI-generated FastAPI client without changing presentation components.
 */
export interface SafetyApi {
  getDashboard(): Promise<DashboardSnapshot>;
  getCameras(): Promise<Camera[]>;
  getIncidents(): Promise<Incident[]>;
  getModels(): Promise<ModelVersion[]>;
}

export class MockSafetyApi implements SafetyApi {
  async getDashboard() {
    return structuredClone(dashboard);
  }
  async getCameras() {
    return structuredClone(cameras);
  }
  async getIncidents() {
    return structuredClone(incidents);
  }
  async getModels() {
    return structuredClone(modelVersions);
  }
}

export const safetyApi: SafetyApi = new MockSafetyApi();

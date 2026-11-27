
import { useState } from "react";
import { Card, SectionHeader, StatusPill } from "./components/ui";

type Site = {
  id: string;
  name: string;
};

type Camera = {
  id: string;
  name: string;
};

type Incident = {
  id: string;
  violation_type: string;
  status: string;
  detected_at: string;
  site_id?: string;
  camera_id?: string | null;
};

type IncidentPage = {
  items: Incident[];
  total: number;
};

type Props = {
  incidents: IncidentPage | null;
  sites: Site[];
  cameras: Camera[];
  updateStatus?: (id: string, status: "acknowledged" | "resolved") => void;
  statusBusy: boolean;
};

function statusTone(
  status: string
): "blue" | "warning" | "success" | "neutral" {
  switch (status) {
    case "open":
      return "blue";
    case "acknowledged":
      return "warning";
    case "resolved":
      return "success";
    default:
      return "neutral";
  }
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString();
}

export default function RealIncidentTable({
  incidents,
  sites,
  cameras,
  updateStatus,
  statusBusy,
}: Props) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const loaded = incidents?.items ?? [];

  const filtered = loaded.filter((incident) => {
    const site = sites.find(
      (item) => item.id === incident.site_id
    );

    const camera = cameras.find(
      (item) => item.id === incident.camera_id
    );

    const searchText = [
      incident.id,
      incident.violation_type,
      incident.status,
      site?.name ?? "",
      camera?.name ?? "",
    ]
      .join(" ")
      .toLowerCase();

    const matchesSearch = searchText.includes(
      search.trim().toLowerCase()
    );

    const matchesStatus =
      statusFilter === "all" ||
      incident.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  return (
    <div id="incidents" className="mt-6">
      <Card>
        <SectionHeader
          title="PPE Incidents"
          subtitle="Recorded incidents from FastAPI and PostgreSQL"
        />

        <div className="table-toolbar flex flex-wrap items-center justify-between gap-3">
          <label className="inline-search flex items-center gap-2">
            <input
              type="search"
              aria-label="Search incidents"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search incidents..."
              className="w-full bg-transparent"
            />
          </label>

          <div className="flex items-center gap-3">
            <select
              aria-label="Filter incidents by status"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value)
              }
              className="rounded-md border bg-white px-3 py-2"
            >
              <option value="all">All statuses</option>
              <option value="open">Open</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
            </select>

            <span className="result-count">
              {filtered.length} displayed
            </span>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Incident</th>
                <th>Site</th>
                <th>Camera</th>
                <th>Detected</th>
                <th>Status</th>
              </tr>
            </thead>

            <tbody>
              {filtered.map((incident) => {
                const site = sites.find(
                  (item) => item.id === incident.site_id
                );

                const camera = cameras.find(
                  (item) => item.id === incident.camera_id
                );

                return (
                  <tr key={incident.id}>
                    <td>
                      <div className="incident-name">
                        <div>
                          <strong>
                            {incident.violation_type.replace(
                              /_/g,
                              " "
                            )}
                          </strong>
                          <small>{incident.id}</small>
                        </div>
                      </div>
                    </td>

                    <td>
                      {site?.name ??
                        incident.site_id ??
                        "Not available"}
                    </td>

                    <td>
                      {camera?.name ??
                        (incident.camera_id
                          ? incident.camera_id
                          : "Not linked")}
                    </td>

                    <td>
                      {formatDate(incident.detected_at)}
                    </td>

                    <td>
                      <StatusPill
                        tone={statusTone(incident.status)}
                      >
                        {incident.status}
                      </StatusPill>
                      {updateStatus && (incident.status === "open" || incident.status === "acknowledged") && (
                        <button
                          type="button"
                          className="ml-2 rounded border px-2 py-1 disabled:opacity-50"
                          disabled={statusBusy}
                          onClick={() => updateStatus(incident.id,
                            incident.status === "open" ? "acknowledged" : "resolved")}
                        >
                          {incident.status === "open" ? "Acknowledge" : "Resolve"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}

              {filtered.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="py-8 text-center"
                  >
                    {loaded.length === 0
                      ? "No incidents recorded in this organization."
                      : "No incidents match the selected filters."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="border-t px-5 py-3 text-xs text-slate-500">
          Showing {filtered.length} of {loaded.length} loaded
          incidents ({incidents?.total ?? "—"} total recorded).
          Confidence, severity and AI evidence are not
          available in this API response.
        </div>
      </Card>
    </div>
  );
}

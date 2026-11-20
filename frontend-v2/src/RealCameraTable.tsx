
import { useState } from "react";
import { Card, Icon, SectionHeader, StatusPill } from "./components/ui";

type Site = {
  id: string;
  name: string;
};

type Camera = {
  id: string;
  site_id: string;
  name: string;
  enabled: boolean;
  stream_ref: string;
};

type Props = {
  sites: Site[];
  cameras: Camera[];
};

export default function RealCameraTable({ sites, cameras }: Props) {
  const [search, setSearch] = useState("");

  const filtered = cameras.filter((camera) => {
    const site = sites.find((s) => s.id === camera.site_id);
    const text = [
      camera.name,
      camera.id,
      camera.stream_ref,
      site?.name ?? "",
    ].join(" ").toLowerCase();

    return text.includes(search.trim().toLowerCase());
  });

  return (
    <div id="cameras">
      <Card>
        <SectionHeader
          title="Sites & Cameras"
          subtitle="Camera configuration from FastAPI and PostgreSQL"
        />

        <div className="table-toolbar flex flex-wrap items-center justify-between gap-3">
          <label className="inline-search flex items-center gap-2">
            <Icon name="search" size={17} />
            <input
              type="search"
              aria-label="Search cameras"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search cameras or sites..."
              className="w-full bg-transparent"
            />
          </label>

          <span className="result-count">
            Showing {filtered.length} of {cameras.length} cameras
          </span>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Camera</th>
                <th>Site</th>
                <th>Configuration</th>
                <th>Live health</th>
                <th>Stream reference</th>
              </tr>
            </thead>

            <tbody>
              {filtered.map((camera) => {
                const site = sites.find(
                  (item) => item.id === camera.site_id
                );

                return (
                  <tr key={camera.id}>
                    <td>
                      <div className="camera-cell">
                        <div className="metric-icon tone-blue">
                          <Icon name="camera" size={19} />
                        </div>
                        <div>
                          <strong>{camera.name}</strong>
                          <small>{camera.id}</small>
                        </div>
                      </div>
                    </td>

                    <td>{site?.name ?? "Unknown site"}</td>

                    <td>
                      <StatusPill
                        tone={camera.enabled ? "blue" : "neutral"}
                      >
                        {camera.enabled ? "Enabled" : "Disabled"}
                      </StatusPill>
                    </td>

                    <td>
                      <StatusPill tone="neutral">
                        Not monitored
                      </StatusPill>
                    </td>

                    <td>
                      <code>{camera.stream_ref}</code>
                    </td>
                  </tr>
                );
              })}

              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center py-8">
                    {search
                      ? "No cameras match your search."
                      : "No cameras configured for this organization."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="border-t px-5 py-3 text-xs text-slate-500">
          Configuration enabled does not mean the camera is online.
          Live streaming and camera health monitoring are not active.
        </div>
      </Card>
    </div>
  );
}


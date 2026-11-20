
import { useState, type FormEvent } from "react";

type Membership = {
  organization_id: string;
  role: string;
};

type CurrentUser = {
  email: string;
  memberships: Membership[];
};

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

type Incident = {
  id: string;
  violation_type: string;
  status: string;
  detected_at: string;
};

type IncidentPage = {
  items: Incident[];
  total: number;
};

async function api<T>(
  path: string,
  options: RequestInit = {},
  token?: string
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "omit",
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export default function IntegrationApp() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [organizationId, setOrganizationId] = useState("");
  const [sites, setSites] = useState<Site[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [incidents, setIncidents] = useState<IncidentPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function loadData(accessToken: string, orgId: string) {
    setBusy(true);
    setError("");

    try {
      const prefix = `/api/v1/organizations/${encodeURIComponent(orgId)}`;

      const [siteData, incidentData] = await Promise.all([
        api<Site[]>(`${prefix}/sites`, {}, accessToken),
        api<IncidentPage>(
          `${prefix}/incidents?limit=100&offset=0`,
          {},
          accessToken
        ),
      ]);

      const cameraGroups = await Promise.all(
        siteData.map((site) =>
          api<Camera[]>(
            `${prefix}/sites/${encodeURIComponent(site.id)}/cameras`,
            {},
            accessToken
          )
        )
      );

      setSites(siteData);
      setCameras(cameraGroups.flat());
      setIncidents(incidentData);
    } catch (err) {
      setError(
        err instanceof Error
          ? `Data request failed: ${err.message}`
          : "Unable to load data"
      );
    } finally {
      setBusy(false);
    }
  }

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const auth = await api<{ access_token: string }>(
        "/api/v1/auth/login",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        }
      );

      const me = await api<CurrentUser>(
        "/api/v1/auth/me",
        {},
        auth.access_token
      );

      const membership = me.memberships[0];

      if (!membership) {
        throw new Error("No organization membership");
      }

      setUser(me);
      setToken(auth.access_token);
      setOrganizationId(membership.organization_id);

      await loadData(auth.access_token, membership.organization_id);
    } catch (err) {
      setError(
        err instanceof Error && err.message === "HTTP 401"
          ? "Invalid email or password"
          : "Login failed. Check API connectivity and account access."
      );
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  async function logout() {
    let confirmed = true;

    if (token) {
      try {
        await api<void>(
          "/api/v1/auth/logout",
          { method: "POST" },
          token
        );
      } catch {
        confirmed = false;
      }
    }

    setToken(null);
    setUser(null);
    setOrganizationId("");
    setSites([]);
    setCameras([]);
    setIncidents(null);
    setPassword("");
    setError(
      confirmed ? "" : "Server logout could not be confirmed."
    );
  }

  if (!token || !user) {
    return (
      <main className="min-h-screen bg-slate-100 flex items-center justify-center p-6">
        <form
          onSubmit={login}
          className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl"
        >
          <div className="mb-7">
            <div className="text-2xl font-bold text-blue-600">
              SafeSite AI
            </div>
            <h1 className="mt-5 text-xl font-bold">
              PPE V2 Sign In
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              Integration testing environment
            </p>
          </div>

          <label className="block mb-4">
            <span className="text-sm font-semibold">Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-2 w-full rounded-lg border p-3"
            />
          </label>

          <label className="block mb-5">
            <span className="text-sm font-semibold">Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-2 w-full rounded-lg border p-3"
            />
          </label>

          {error && (
            <p role="alert" className="mb-4 text-sm text-red-600">
              {error}
            </p>
          )}

          <button
            disabled={busy}
            className="w-full rounded-lg bg-blue-600 p-3 font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-100 p-5 md:p-10">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              SafeSite AI — Backend Integration
            </h1>
            <p className="text-sm text-slate-500">
              Signed in: {user.email}
            </p>
          </div>

          <button
            onClick={logout}
            className="rounded-lg bg-slate-900 px-5 py-3 text-white"
          >
            Sign out
          </button>
        </header>

        <div className="my-7 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
          Real PostgreSQL data. CCTV streaming, AI detection,
          compliance metrics and live camera health are not enabled.
        </div>

        <div className="mb-5 flex flex-wrap items-center gap-3">
          <label className="text-sm font-medium">
            Organization
            <select
              className="ml-2 rounded-lg border bg-white p-2"
              value={organizationId}
              onChange={(e) => {
                const id = e.target.value;
                setOrganizationId(id);
                setSites([]);
                setCameras([]);
                setIncidents(null);
                void loadData(token, id);
              }}
            >
              {user.memberships.map((m) => (
                <option
                  key={m.organization_id}
                  value={m.organization_id}
                >
                  {m.organization_id} ({m.role})
                </option>
              ))}
            </select>
          </label>

          <button
            disabled={busy}
            onClick={() => void loadData(token, organizationId)}
            className="rounded-lg border bg-white px-4 py-2 disabled:opacity-50"
          >
            {busy ? "Loading..." : "Refresh data"}
          </button>
        </div>

        {error && (
          <p role="alert" className="mb-5 text-red-600">
            {error}
          </p>
        )}

        <div className="grid gap-4 md:grid-cols-3">
          {[
            ["Registered Sites", sites.length],
            ["Configured Cameras", cameras.length],
            ["Total Incidents", incidents?.total ?? "—"],
          ].map(([label, value]) => (
            <section
              key={label}
              className="rounded-xl bg-white p-6 shadow-sm"
            >
              <p className="text-sm text-slate-500">{label}</p>
              <strong className="mt-2 block text-3xl">
                {value}
              </strong>
            </section>
          ))}
        </div>

        <section className="mt-6 rounded-xl bg-white p-6">
          <h2 className="mb-4 text-lg font-bold">
            Sites and Cameras
          </h2>

          {cameras.length === 0 && (
            <p>No cameras returned by the API.</p>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="p-3">Camera</th>
                  <th className="p-3">Site</th>
                  <th className="p-3">Configured</th>
                  <th className="p-3">Stream reference</th>
                </tr>
              </thead>
              <tbody>
                {cameras.map((camera) => (
                  <tr key={camera.id} className="border-b">
                    <td className="p-3">{camera.name}</td>
                    <td className="p-3">
                      {sites.find((s) => s.id === camera.site_id)?.name ?? "Unknown"}
                    </td>
                    <td className="p-3">
                      {camera.enabled ? "Enabled" : "Disabled"}
                    </td>
                    <td className="p-3">{camera.stream_ref}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mt-6 rounded-xl bg-white p-6">
          <h2 className="mb-4 text-lg font-bold">
            Incidents
          </h2>
          <p className="mb-3 text-sm text-slate-500">
            Showing {incidents?.items.length ?? 0} of{" "}
            {incidents?.total ?? "—"} incidents
          </p>
          {incidents?.items.length === 0 && (
            <p>No incidents recorded in this test organization.</p>
          )}
          {incidents?.items.map((incident) => (
            <div key={incident.id} className="border-t py-3 text-sm">
              {incident.violation_type} — {incident.status}
              <span className="ml-3 text-slate-500">
                {incident.detected_at}
              </span>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}

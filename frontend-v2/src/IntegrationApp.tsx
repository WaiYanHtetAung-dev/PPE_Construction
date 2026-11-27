import RealIncidentTable from "./RealIncidentTable";
import RealCameraTable from "./RealCameraTable";
import RealMetrics from "./RealMetrics";
import FigmaShell from "./FigmaShell";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

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

class ApiError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

const sessionExpired = "Your session has ended. Sign in again.";

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
    throw new ApiError(response.status);
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
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [organizationId, setOrganizationId] = useState("");
  const [sites, setSites] = useState<Site[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [incidents, setIncidents] = useState<IncidentPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dataRequest = useRef<AbortController | null>(null);

  const clearSession = useCallback((message: string) => {
    dataRequest.current?.abort();
    dataRequest.current = null;
    setToken(null);
    setExpiresAt(null);
    setUser(null);
    setOrganizationId("");
    setSites([]);
    setCameras([]);
    setIncidents(null);
    setPassword("");
    setBusy(false);
    setError(message);
  }, []);

  const expireSession = useCallback(() => clearSession(sessionExpired), [clearSession]);

  useEffect(() => {
    if (expiresAt === null) return;
    const timeout = window.setTimeout(() => clearSession(sessionExpired),
      Math.max(0, expiresAt - Date.now()));
    return () => window.clearTimeout(timeout);
  }, [expiresAt, clearSession]);

  async function loadData(accessToken: string, orgId: string) {
    dataRequest.current?.abort();
    const request = new AbortController();
    dataRequest.current = request;
    const options = { signal: request.signal };
    setBusy(true);
    setError("");

    try {
      const prefix = `/api/v1/organizations/${encodeURIComponent(orgId)}`;

      const [siteData, incidentData] = await Promise.all([
        api<Site[]>(`${prefix}/sites`, options, accessToken),
        api<IncidentPage>(
          `${prefix}/incidents?limit=100&offset=0`,
          options,
          accessToken
        ),
      ]);

      const cameraGroups = await Promise.all(
        siteData.map((site) =>
          api<Camera[]>(
            `${prefix}/sites/${encodeURIComponent(site.id)}/cameras`,
            options,
            accessToken
          )
        )
      );

      if (dataRequest.current !== request) return;
      setSites(siteData);
      setCameras(cameraGroups.flat());
      setIncidents(incidentData);
    } catch (err) {
      if (dataRequest.current !== request) return;
      if (err instanceof ApiError && err.status === 401) {
        clearSession(sessionExpired);
        return;
      }
      setError(
        err instanceof Error
          ? `Data request failed: ${err.message}`
          : "Unable to load data"
      );
    } finally {
      if (dataRequest.current === request) {
        request.abort();
        dataRequest.current = null;
        setBusy(false);
      }
    }
  }

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const auth = await api<{ access_token: string; expires_at: string }>(
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

      const expiration = Date.parse(auth.expires_at);
      if (!Number.isFinite(expiration) || expiration <= Date.now()) {
        clearSession(sessionExpired);
        return;
      }

      setUser(me);
      setToken(auth.access_token);
      setExpiresAt(expiration);
      setOrganizationId(membership.organization_id);

      void loadData(auth.access_token, membership.organization_id);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Invalid email or password"
          : "Login failed. Check API connectivity and account access."
      );
    } finally {
      setPassword("");
      if (!dataRequest.current) setBusy(false);
    }
  }

  async function logout() {
    clearSession("");
    if (!token) return;
    setBusy(true);
    try {
      await api<void>("/api/v1/auth/logout", { method: "POST" }, token);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) {
        setError("Server logout could not be confirmed.");
      }
    } finally {
      setBusy(false);
    }
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
    <FigmaShell userEmail={user.email} onLogout={() => void logout()}>
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

        </header>

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

        <RealMetrics
          siteCount={sites.length}
          cameraCount={cameras.length}
          incidentTotal={incidents?.total ?? null}
        />

        <RealCameraTable
          key={organizationId}
          sites={sites}
          cameras={cameras}
          organizationId={organizationId}
          token={token}
          expireSession={expireSession}
        />

        <RealIncidentTable
          incidents={incidents}
          sites={sites}
          cameras={cameras}
        />
      </div>
    </FigmaShell>
  );
}

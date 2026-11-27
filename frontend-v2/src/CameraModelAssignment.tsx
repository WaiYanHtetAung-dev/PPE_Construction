import { useEffect, useState } from "react";
import { api, ApiError } from "./services/api";

type Assignment = {
  revision: number;
  model_version: { id: string; model_key: string; version: string } | null;
};

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; assignment: Assignment };

type Props = {
  organizationId: string;
  cameraId: string;
  token: string;
  expireSession: () => void;
};

export default function CameraModelAssignment({ organizationId, cameraId, token, expireSession }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const request = new AbortController();
    const deadline = window.setTimeout(() => request.abort(), 10000);
    const organization = encodeURIComponent(organizationId);
    const camera = encodeURIComponent(cameraId);
    let disposed = false;

    api<Assignment>(`/api/v1/organizations/${organization}/cameras/${camera}/model`,
      { signal: request.signal }, token)
      .then((assignment) => {
        if (!disposed) setState({ status: "loaded", assignment });
      })
      .catch((err: unknown) => {
        if (disposed) return;
        if (err instanceof ApiError && err.status === 401) {
          expireSession();
          return;
        }
        setState({
          status: "error",
          message: err instanceof ApiError && err.status === 404
            ? "Model assignment is unavailable for this camera."
            : "Could not load the model assignment.",
        });
      })
      .finally(() => window.clearTimeout(deadline));

    return () => {
      disposed = true;
      window.clearTimeout(deadline);
      request.abort();
    };
  }, [attempt, cameraId, expireSession, organizationId, token]);

  if (state.status === "loading") {
    return <span role="status">Loading model assignment…</span>;
  }

  return (
    <div className="flex flex-col items-start gap-1">
      {state.status === "error" ? (
        <span role="alert">{state.message}</span>
      ) : (
        <>
          {state.assignment.model_version ? (
            <span>
              {state.assignment.model_version.model_key} · Version {state.assignment.model_version.version}
            </span>
          ) : <span>No model assigned</span>}
          {Number.isSafeInteger(state.assignment.revision) && (
            <small>Assignment revision {state.assignment.revision}</small>
          )}
        </>
      )}
      <button type="button" onClick={() => {
        setState({ status: "loading" });
        setAttempt((value) => value + 1);
      }}>Refresh model assignment</button>
    </div>
  );
}

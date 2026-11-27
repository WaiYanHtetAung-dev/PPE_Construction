import { useEffect, useState } from "react";
import { StatusPill } from "./components/ui";

type MediaStatus = {
  state: "disabled" | "not_monitored" | "offline" | "online";
  preview_available: boolean;
};

const labels = { disabled: "Disabled", not_monitored: "Not monitored", offline: "Offline", online: "Online" };

type Props = { cameraId: string; organizationId: string; token: string; expireSession: () => void };

export default function CameraMediaPreview({ cameraId, organizationId, token, expireSession }: Props) {
  const base = `/api/v1/organizations/${encodeURIComponent(organizationId)}/cameras/${encodeURIComponent(cameraId)}/media`;
  const [status, setStatus] = useState<MediaStatus | null>(null);
  const [error, setError] = useState("");
  const [statusRequest, setStatusRequest] = useState(1);
  const [clipRequest, setClipRequest] = useState(0);
  const [clip, setClip] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`${base}/status`, {
          headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
          credentials: "omit", signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (response.status === 401) return expireSession();
        if (!response.ok) throw new Error();
        const mediaStatus = await response.json() as MediaStatus;
        if (!controller.signal.aborted) setStatus(mediaStatus);
      } catch {
        if (!controller.signal.aborted) setError("Camera status unavailable");
      }
    })();
    return () => controller.abort();
  }, [base, expireSession, statusRequest, token]);

  useEffect(() => {
    if (!clipRequest) return;
    const controller = new AbortController();
    let objectUrl: string | undefined;
    void (async () => {
      try {
        const response = await fetch(`${base}/preview`, {
          headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
          credentials: "omit", signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (response.status === 401) return expireSession();
        if (!response.ok || response.headers.get("Content-Type") !== "video/mp4") throw new Error();
        const video = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(video);
        setClip(objectUrl);
      } catch {
        if (!controller.signal.aborted) setError("Camera preview unavailable");
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [base, clipRequest, expireSession, token]);

  return (
    <div className="flex flex-col items-start gap-2">
      {status && <StatusPill tone={status.state === "online" ? "blue" : "neutral"}>{labels[status.state]}</StatusPill>}
      {error && <span role="alert">{error}</span>}
      {!error && !status && <span role="status">Checking status…</span>}
      <button type="button" onClick={() => {
        setError("");
        setStatus(null);
        setClipRequest(0);
        setClip(null);
        setStatusRequest((request) => request + 1);
      }}>Refresh camera status</button>
      {status?.preview_available && <button type="button" onClick={() => {
        setError("");
        setClip(null);
        setClipRequest((request) => request + 1);
      }}>Load video preview</button>}
      {clip && <video src={clip} controls playsInline aria-label="Camera video preview" className="max-w-64" />}
    </div>
  );
}

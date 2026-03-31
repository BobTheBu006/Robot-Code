import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import { getCameraStreamUrl } from "../lib/api";
import type { CameraStatus } from "../types/robot";

type RequestStatus = "loading" | "success" | "error";

interface CameraFeedCardProps {
  cameraStatus: CameraStatus | null;
  status: RequestStatus;
  error: string | null;
}

function getBadgeConfig(status: RequestStatus, available: boolean | undefined) {
  if (status === "error" || available === false) {
    return { label: "Offline", tone: "offline" as const };
  }

  if (status === "success" && available) {
    return { label: "Live", tone: "online" as const };
  }

  return { label: "Loading", tone: "neutral" as const };
}

export function CameraFeedCard({ cameraStatus, status, error }: CameraFeedCardProps) {
  const badge = getBadgeConfig(status, cameraStatus?.available);
  const hasFeed = status === "success" && cameraStatus?.available;

  return (
    <Panel
      title="Camera Feed"
      subtitle="Live USB camera stream from the Raspberry Pi backend"
      headerAction={<StatusBadge label={badge.label} tone={badge.tone} />}
    >
      {hasFeed ? (
        <div className="camera-feed">
          <img
            className="camera-feed__image"
            src={getCameraStreamUrl()}
            alt="Live robot camera feed"
          />
          <div className="camera-feed__meta">
            <span>Device: {cameraStatus?.active_device ?? cameraStatus?.configured_device}</span>
            <span>
              {cameraStatus?.width ?? "?"} x {cameraStatus?.height ?? "?"}
              {cameraStatus?.fps ? ` at ${cameraStatus.fps} FPS` : ""}
            </span>
          </div>
        </div>
      ) : (
        <div className="placeholder-box">
          <div>
            <p>{error ?? cameraStatus?.error ?? "Checking for a connected camera..."}</p>
            <p className="muted-text">
              Expected camera source: {cameraStatus?.configured_device ?? "0"}
            </p>
          </div>
        </div>
      )}
    </Panel>
  );
}

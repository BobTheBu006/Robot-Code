import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import { getCameraStreamUrl } from "../lib/api";
import type { CameraStatus } from "../types/robot";

type RequestStatus = "loading" | "success" | "error";

interface CameraFeedCardProps {
  cameraStatus: CameraStatus | null;
  status: RequestStatus;
  error: string | null;
  isToggling: boolean;
  onTogglePower: () => void;
}

function getBadgeConfig(
  status: RequestStatus,
  enabled: boolean | undefined,
  available: boolean | undefined,
) {
  if (enabled === false) {
    return { label: "Off", tone: "neutral" as const };
  }

  if (status === "error" || available === false) {
    return { label: "Offline", tone: "offline" as const };
  }

  if (status === "success" && available) {
    return { label: "Live", tone: "online" as const };
  }

  return { label: "Loading", tone: "neutral" as const };
}

export function CameraFeedCard({
  cameraStatus,
  status,
  error,
  isToggling,
  onTogglePower,
}: CameraFeedCardProps) {
  const badge = getBadgeConfig(status, cameraStatus?.enabled, cameraStatus?.available);
  const hasFeed = cameraStatus?.enabled && cameraStatus?.available;
  const isEnabled = cameraStatus?.enabled ?? false;

  return (
    <Panel
      title="Camera Feed"
      subtitle="Live USB camera stream from the Raspberry Pi backend. Off by default and auto turns off after 5 minutes."
      headerAction={
        <div className="camera-feed__actions">
          <button
            className={`camera-feed__power ${isEnabled ? "camera-feed__power--on" : "camera-feed__power--off"}`}
            disabled={isToggling}
            onClick={onTogglePower}
            type="button"
          >
            {isToggling ? "Switching..." : isEnabled ? "Turn Off" : "Turn On"}
          </button>
          <StatusBadge label={badge.label} tone={badge.tone} />
        </div>
      }
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
            <p>
              {error ?? cameraStatus?.error ?? (cameraStatus?.enabled === false ? "Camera is turned off." : "Checking for a connected camera...")}
            </p>
            <p className="muted-text">
              Expected camera source: {cameraStatus?.configured_device ?? "0"}
            </p>
          </div>
        </div>
      )}
    </Panel>
  );
}

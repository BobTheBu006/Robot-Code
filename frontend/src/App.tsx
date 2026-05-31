import { useEffect, useState } from "react";
import { CameraFeedCard } from "./components/CameraFeedCard";
import { HardwareDiagramCard } from "./components/HardwareDiagramCard";
import { RobotStateCard } from "./components/RobotStateCard";
import { StatusBadge } from "./components/StatusBadge";
import { WorkflowEditorCard } from "./components/workflow/WorkflowEditorCard";
import { fetchCameraStatus, fetchHealth, fetchRobotState, setCameraPower } from "./lib/api";
import type { CameraStatus, HealthResponse, RobotState } from "./types/robot";

type RequestStatus = "loading" | "success" | "error";

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [cameraStatus, setCameraStatus] = useState<CameraStatus | null>(null);
  const [robotState, setRobotState] = useState<RobotState | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<RequestStatus>("loading");
  const [cameraFeedStatus, setCameraFeedStatus] = useState<RequestStatus>("loading");
  const [robotStateStatus, setRobotStateStatus] = useState<RequestStatus>("loading");
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [cameraFeedError, setCameraFeedError] = useState<string | null>(null);
  const [isCameraToggling, setIsCameraToggling] = useState(false);
  const [robotStateError, setRobotStateError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [hardwareMapRevision, setHardwareMapRevision] = useState(0);

  async function loadDashboard() {
    const [healthResult, cameraResult, robotStateResult] = await Promise.allSettled([
      fetchHealth(),
      fetchCameraStatus(),
      fetchRobotState(),
    ]);

    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value);
      setConnectionStatus("success");
      setConnectionError(null);
    } else {
      setConnectionStatus("error");
      setConnectionError(healthResult.reason instanceof Error ? healthResult.reason.message : "Could not reach backend health endpoint");
    }

    if (cameraResult.status === "fulfilled") {
      setCameraStatus(cameraResult.value);
      setCameraFeedStatus("success");
      setCameraFeedError(cameraResult.value.error);
    } else {
      setCameraFeedStatus("error");
      setCameraFeedError(cameraResult.reason instanceof Error ? cameraResult.reason.message : "Could not load camera status");
    }

    if (robotStateResult.status === "fulfilled") {
      setRobotState(robotStateResult.value);
      setRobotStateStatus("success");
      setRobotStateError(null);
      setLastUpdated(new Date().toLocaleTimeString());
    } else {
      setRobotStateStatus("error");
      setRobotStateError(robotStateResult.reason instanceof Error ? robotStateResult.reason.message : "Could not load robot state");
    }
  }

  useEffect(() => {
    let isMounted = true;

    const refreshDashboard = async () => {
      await loadDashboard();
      if (!isMounted) {
        return;
      }
    };

    void refreshDashboard();
    const intervalId = window.setInterval(() => {
      void refreshDashboard();
    }, 1000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  async function handleToggleCameraPower() {
    const nextEnabled = !(cameraStatus?.enabled ?? false);
    setIsCameraToggling(true);

    try {
      const nextStatus = await setCameraPower(nextEnabled);
      setCameraStatus(nextStatus);
      setCameraFeedStatus("success");
      setCameraFeedError(nextStatus.error);
    } catch (error) {
      setCameraFeedStatus("error");
      setCameraFeedError(error instanceof Error ? error.message : "Could not change camera power state");
    } finally {
      setIsCameraToggling(false);
    }
  }

  const isConnected = connectionStatus === "success";

  return (
    <main className="app-shell">
      <div className="app-shell__inner">
        <header className="hero">
          <div>
            <p className="eyebrow">Local Raspberry Pi Controller</p>
            <h1>Robot Control Dashboard</h1>
            <p className="hero__description">
              Mock robot state is fetched from the FastAPI backend every second so the dashboard stays live while the hardware layer is still under development.
            </p>
          </div>
          <div className="hero__status">
            <span>Backend status</span>
            <StatusBadge
              label={isConnected ? "Connected" : connectionStatus === "loading" ? "Checking" : "Disconnected"}
              tone={isConnected ? "online" : connectionStatus === "loading" ? "neutral" : "offline"}
            />
            <small>
              {connectionError ?? (lastUpdated ? `Last robot-state refresh at ${lastUpdated}` : "Waiting for first response")}
            </small>
          </div>
        </header>

        <div className="overview-grid">
          <RobotStateCard
            robotState={robotState}
            status={robotStateStatus}
            error={robotStateError}
            lastUpdated={lastUpdated}
          />

          <CameraFeedCard
            cameraStatus={cameraStatus}
            status={cameraFeedStatus}
            error={cameraFeedError}
            isToggling={isCameraToggling}
            onTogglePower={handleToggleCameraPower}
          />
        </div>

        <WorkflowEditorCard hardwareMapRevision={hardwareMapRevision} />

        <HardwareDiagramCard onHardwareMapSaved={() => setHardwareMapRevision((revision) => revision + 1)} />
      </div>
    </main>
  );
}

export default App;

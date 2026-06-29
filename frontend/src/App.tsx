import { useEffect, useState } from "react";
import { CameraFeedCard } from "./components/CameraFeedCard";
import { HardwareDiagramCard } from "./components/HardwareDiagramCard";
import { RobotStateCard } from "./components/RobotStateCard";
import { StatusBadge } from "./components/StatusBadge";
import { WorkflowEditorCard } from "./components/workflow/WorkflowEditorCard";
import { emergencyStop, fetchCameraStatus, fetchHealth, fetchRobotState, setCameraPower } from "./lib/api";
import type { CameraStatus, HealthResponse, RobotState } from "./types/robot";

type RequestStatus = "loading" | "success" | "error";
type AppPage = "dashboard" | "workflow-editor" | "function-map" | "hardware-map";

const APP_PAGES: Array<{ id: AppPage; label: string }> = [
  { id: "dashboard", label: "Dashboard" },
  { id: "workflow-editor", label: "Workflow Editor" },
  { id: "function-map", label: "Function Map" },
  { id: "hardware-map", label: "Hardware Map" },
];

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [cameraStatus, setCameraStatus] = useState<CameraStatus | null>(null);
  const [robotState, setRobotState] = useState<RobotState | null>(null);
  const [activePage, setActivePage] = useState<AppPage>("dashboard");
  const [connectionStatus, setConnectionStatus] = useState<RequestStatus>("loading");
  const [cameraFeedStatus, setCameraFeedStatus] = useState<RequestStatus>("loading");
  const [robotStateStatus, setRobotStateStatus] = useState<RequestStatus>("loading");
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [cameraFeedError, setCameraFeedError] = useState<string | null>(null);
  const [isCameraToggling, setIsCameraToggling] = useState(false);
  const [robotStateError, setRobotStateError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [hardwareMapRevision, setHardwareMapRevision] = useState(0);
  const [emergencyStopState, setEmergencyStopState] = useState<"idle" | "stopping" | "sent" | "error">("idle");
  const [emergencyStopMessage, setEmergencyStopMessage] = useState<string | null>(null);

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

  useEffect(() => {
    // Starting a new run clears any latched E-Stop so the control returns to
    // its armed "E-STOP" state instead of staying on "RESUME".
    const handleEmergencyReset = () => {
      setEmergencyStopState("idle");
      setEmergencyStopMessage(null);
    };
    window.addEventListener("robot-emergency-reset", handleEmergencyReset);
    return () => {
      window.removeEventListener("robot-emergency-reset", handleEmergencyReset);
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

  async function handleEmergencyStop() {
    if (emergencyStopState === "sent") {
      window.dispatchEvent(new CustomEvent("robot-emergency-resume"));
      setEmergencyStopState("idle");
      setEmergencyStopMessage("Flow resumed");
      return;
    }

    window.dispatchEvent(new CustomEvent("robot-emergency-stop"));
    setEmergencyStopState("stopping");
    setEmergencyStopMessage("Stopping now");

    try {
      const response = await emergencyStop();
      setEmergencyStopState(response.ok ? "sent" : "error");
      setEmergencyStopMessage(response.message);
    } catch (error) {
      setEmergencyStopState("error");
      setEmergencyStopMessage(error instanceof Error ? error.message : "Emergency stop request failed");
    }
  }

  const isConnected = connectionStatus === "success";
  const activePageLabel = APP_PAGES.find((page) => page.id === activePage)?.label ?? "Dashboard";

  function handleHardwareMapSaved() {
    setHardwareMapRevision((revision) => revision + 1);
  }

  function renderActivePage() {
    if (activePage === "dashboard") {
      return (
        <>
          <section className="page-heading">
            <p className="eyebrow">Local Raspberry Pi Controller</p>
            <h1>Dashboard</h1>
          </section>
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
        </>
      );
    }

    if (activePage === "workflow-editor") {
      return <WorkflowEditorCard hardwareMapRevision={hardwareMapRevision} />;
    }

    if (activePage === "function-map") {
      return <HardwareDiagramCard onHardwareMapSaved={handleHardwareMapSaved} view="function-map" />;
    }

    return <HardwareDiagramCard onHardwareMapSaved={handleHardwareMapSaved} view="hardware-map" />;
  }

  const appShellClassName = activePage === "workflow-editor" || activePage === "hardware-map"
    ? "app-shell app-shell--no-scroll"
    : "app-shell";

  return (
    <main className={appShellClassName}>
      <header className="app-header">
        <div className="app-header__inner">
          <div className="app-header__identity">
            <span>Robot Control</span>
            <strong>{activePageLabel}</strong>
          </div>
          <nav aria-label="Primary pages" className="app-nav">
            {APP_PAGES.map((page) => (
              <button
                aria-current={activePage === page.id ? "page" : undefined}
                className={activePage === page.id ? "app-nav__item app-nav__item--active" : "app-nav__item"}
                key={page.id}
                onClick={() => setActivePage(page.id)}
                type="button"
              >
                {page.label}
              </button>
            ))}
          </nav>
          <div className="app-header__status">
            <span>Backend</span>
            <StatusBadge
              label={isConnected ? "Connected" : connectionStatus === "loading" ? "Checking" : "Disconnected"}
              tone={isConnected ? "online" : connectionStatus === "loading" ? "neutral" : "offline"}
            />
            <small>
              {connectionError ?? (lastUpdated ? `Updated ${lastUpdated}` : "Waiting")}
            </small>
          </div>
          <div className="app-header__estop">
            <button
              className={emergencyStopState === "stopping" ? "emergency-stop emergency-stop--active" : "emergency-stop"}
              onClick={() => void handleEmergencyStop()}
              type="button"
            >
              {emergencyStopState === "sent" ? "RESUME" : "E-STOP"}
            </button>
            {emergencyStopMessage ? <span>{emergencyStopMessage}</span> : null}
          </div>
        </div>
      </header>
      <div className="app-shell__inner">
        {renderActivePage()}
      </div>
    </main>
  );
}

export default App;

import { useEffect, useState } from "react";
import { PlaceholderPanel } from "./components/PlaceholderPanel";
import { RobotStateCard } from "./components/RobotStateCard";
import { StatusBadge } from "./components/StatusBadge";
import { fetchHealth, fetchRobotState } from "./lib/api";
import type { HealthResponse, RobotState } from "./types/robot";

type RequestStatus = "loading" | "success" | "error";

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [robotState, setRobotState] = useState<RobotState | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<RequestStatus>("loading");
  const [robotStateStatus, setRobotStateStatus] = useState<RequestStatus>("loading");
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [robotStateError, setRobotStateError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    const loadDashboard = async () => {
      const [healthResult, robotStateResult] = await Promise.allSettled([
        fetchHealth(),
        fetchRobotState(),
      ]);

      if (!isMounted) {
        return;
      }

      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
        setConnectionStatus("success");
        setConnectionError(null);
      } else {
        setConnectionStatus("error");
        setConnectionError(healthResult.reason instanceof Error ? healthResult.reason.message : "Could not reach backend health endpoint");
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
    };

    void loadDashboard();
    const intervalId = window.setInterval(() => {
      void loadDashboard();
    }, 1000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

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

        <div className="dashboard-grid">
          <RobotStateCard
            robotState={robotState}
            status={robotStateStatus}
            error={robotStateError}
            lastUpdated={lastUpdated}
          />

          <PlaceholderPanel
            title="Camera Feed"
            description="Reserved for future live camera monitoring from the Raspberry Pi."
          />

          <PlaceholderPanel
            title="Workflow Editor"
            description="Reserved for future workflow creation, scheduling, and job execution."
          />
        </div>
      </div>
    </main>
  );
}

export default App;

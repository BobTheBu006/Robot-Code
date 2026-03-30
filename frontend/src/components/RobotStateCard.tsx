import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import type { RobotState } from "../types/robot";

type RequestStatus = "loading" | "success" | "error";

interface RobotStateCardProps {
  robotState: RobotState | null;
  status: RequestStatus;
  error: string | null;
  lastUpdated: string | null;
}

function getBadgeConfig(status: RequestStatus) {
  if (status === "success") {
    return { label: "Live", tone: "online" as const };
  }

  if (status === "error") {
    return { label: "Error", tone: "offline" as const };
  }

  return { label: "Loading", tone: "neutral" as const };
}

export function RobotStateCard({ robotState, status, error, lastUpdated }: RobotStateCardProps) {
  const badge = getBadgeConfig(status);
  const activeAlarms = robotState?.alarms.filter((alarm) => alarm.active) ?? [];

  return (
    <Panel
      title="Robot State"
      subtitle="In-memory mock state from the FastAPI backend"
      headerAction={<StatusBadge label={badge.label} tone={badge.tone} />}
    >
      <p className="muted-text">
        Refreshing every 1 second{lastUpdated ? ` - last update at ${lastUpdated}` : ""}
      </p>

      {status === "loading" && !robotState ? <p className="muted-text">Loading robot state...</p> : null}
      {status === "error" ? <p className="error-text">{error ?? "Could not load robot state."}</p> : null}

      {robotState ? (
        <div className="robot-state">
          <div className="kv-grid">
            <div>
              <span className="kv-grid__label">Machine state</span>
              <strong>{robotState.machine_state}</strong>
            </div>
            <div>
              <span className="kv-grid__label">Workflow</span>
              <strong>{robotState.current_workflow ?? "None"}</strong>
            </div>
            <div>
              <span className="kv-grid__label">Current step</span>
              <strong>{robotState.current_step ?? "-"}</strong>
            </div>
          </div>

          <div className="subpanel">
            <h3>Gantry position</h3>
            <div className="position-grid">
              <span>X: {robotState.gantry.x}</span>
              <span>Y: {robotState.gantry.y}</span>
              <span>Z: {robotState.gantry.z}</span>
            </div>
          </div>

          <div className="subpanel">
            <h3>Sensor values</h3>
            <ul className="sensor-list">
              {robotState.sensor_values.map((sensor) => (
                <li key={sensor.name}>
                  <span>{sensor.name}</span>
                  <strong>
                    {sensor.value}
                    {sensor.unit ? ` ${sensor.unit}` : ""}
                  </strong>
                </li>
              ))}
            </ul>
          </div>

          <div className="subpanel">
            <h3>Alarms</h3>
            {activeAlarms.length > 0 ? (
              <ul className="alarm-list">
                {activeAlarms.map((alarm) => (
                  <li key={alarm.code}>
                    <span>{alarm.code}: {alarm.message}</span>
                    <strong>{alarm.severity}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted-text">No active alarms.</p>
            )}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

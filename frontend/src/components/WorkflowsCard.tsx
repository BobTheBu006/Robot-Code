import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import type { WorkflowFileSummary } from "../types/workflow";

type RequestStatus = "loading" | "success" | "error";

interface WorkflowsCardProps {
  workflows: WorkflowFileSummary[];
  defaultFilename: string | null;
  status: RequestStatus;
  error: string | null;
  onOpenWorkflowEditor: () => void;
  onOpenHardwareMap: () => void;
  onOpenFunctionMap: () => void;
}

function getBadgeConfig(status: RequestStatus) {
  if (status === "success") {
    return { label: "Loaded", tone: "online" as const };
  }

  if (status === "error") {
    return { label: "Error", tone: "offline" as const };
  }

  return { label: "Loading", tone: "neutral" as const };
}

function formatUpdatedAt(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatFileSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

export function WorkflowsCard({
  workflows,
  defaultFilename,
  status,
  error,
  onOpenWorkflowEditor,
  onOpenHardwareMap,
  onOpenFunctionMap,
}: WorkflowsCardProps) {
  const badge = getBadgeConfig(status);

  return (
    <Panel
      title="Workflows"
      subtitle="Saved workflows on this Raspberry Pi. Each one runs against the Hardware Map and Function Map below."
      headerAction={<StatusBadge label={badge.label} tone={badge.tone} />}
    >
      <div className="workflows-card__links">
        <button
          className="workflow-editor__action workflow-editor__action--ghost"
          onClick={onOpenWorkflowEditor}
          type="button"
        >
          Open Workflow Editor
        </button>
        <button
          className="workflow-editor__action workflow-editor__action--ghost"
          onClick={onOpenHardwareMap}
          type="button"
        >
          Hardware Map
        </button>
        <button
          className="workflow-editor__action workflow-editor__action--ghost"
          onClick={onOpenFunctionMap}
          type="button"
        >
          Function Map
        </button>
      </div>

      {status === "error" ? <p className="error-text">{error ?? "Could not load the workflow list."}</p> : null}

      {status !== "error" && workflows.length === 0 ? (
        <p className="muted-text">No saved workflows yet. Build one in the Workflow Editor and save it.</p>
      ) : (
        <ul className="workflows-card__list">
          {workflows.map((workflow) => (
            <li key={workflow.path}>
              <div className="workflows-card__list-name">
                <strong>{workflow.filename}</strong>
                {workflow.filename === defaultFilename ? <span className="workflows-card__active-tag">Active</span> : null}
              </div>
              <span className="muted-text">{formatUpdatedAt(workflow.updated_at)} - {formatFileSize(workflow.size_bytes)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

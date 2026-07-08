import { useEffect, useState } from "react";

import { fetchWorkflowList, saveWorkflowToFile } from "../lib/api";
import type { WorkflowFileSummary } from "../types/workflow";
import { Panel } from "./Panel";

interface WorkflowFilesCardProps {
  activeWorkflowFile: string;
  onOpenWorkflow: (filename: string) => void;
}

export function WorkflowFilesCard({ activeWorkflowFile, onOpenWorkflow }: WorkflowFilesCardProps) {
  const [workflows, setWorkflows] = useState<WorkflowFileSummary[]>([]);
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [newWorkflowName, setNewWorkflowName] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  async function loadWorkflowList() {
    try {
      const response = await fetchWorkflowList();
      setWorkflows(response.workflows);
      setStatus("success");
      setError(null);
    } catch (listError) {
      setStatus("error");
      setError(listError instanceof Error ? listError.message : "Could not list workflow files.");
    }
  }

  useEffect(() => {
    void loadWorkflowList();
  }, []);

  async function handleCreateWorkflow() {
    const trimmedName = newWorkflowName.trim();
    if (!trimmedName || isCreating) {
      return;
    }

    setIsCreating(true);
    setError(null);
    try {
      const response = await saveWorkflowToFile([], [], "", trimmedName);
      setNewWorkflowName("");
      await loadWorkflowList();
      onOpenWorkflow(response.filename);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Could not create the workflow file.");
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <Panel
      title="Workflows"
      subtitle="Open a saved workflow in the editor or start a new one."
    >
      <div className="workflow-files">
        <div className="workflow-files__create">
          <input
            onChange={(event) => setNewWorkflowName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleCreateWorkflow();
              }
            }}
            placeholder="new-workflow-name"
            type="text"
            value={newWorkflowName}
          />
          <button
            className="workflow-editor__action workflow-editor__action--primary"
            disabled={!newWorkflowName.trim() || isCreating}
            onClick={() => void handleCreateWorkflow()}
            type="button"
          >
            {isCreating ? "Creating…" : "New workflow"}
          </button>
        </div>

        {error ? <p className="error-text">{error}</p> : null}

        {status === "loading" ? (
          <p className="workflow-files__empty">Loading workflow files…</p>
        ) : workflows.length === 0 ? (
          <p className="workflow-files__empty">No saved workflows yet. Create one above to get started.</p>
        ) : (
          <ul className="workflow-files__list">
            {workflows.map((workflow) => {
              const isActive = workflow.filename === activeWorkflowFile;
              return (
                <li className={isActive ? "workflow-files__item workflow-files__item--active" : "workflow-files__item"} key={workflow.path}>
                  <div className="workflow-files__meta">
                    <strong>{workflow.filename.replace(/\.json$/i, "")}</strong>
                    <span>Updated {new Date(workflow.updated_at).toLocaleString()}</span>
                  </div>
                  <button
                    className="workflow-editor__action workflow-editor__action--ghost"
                    onClick={() => onOpenWorkflow(workflow.filename)}
                    type="button"
                  >
                    {isActive ? "Open (current)" : "Open"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Panel>
  );
}

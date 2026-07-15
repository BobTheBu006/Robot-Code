import { useEffect, useState } from "react";

import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import type { WorkflowFileSummary } from "../types/workflow";

type RequestStatus = "loading" | "success" | "error";
type PendingAction = "create" | "rename" | null;

interface WorkflowsCardProps {
  workflows: WorkflowFileSummary[];
  defaultFilename: string | null;
  status: RequestStatus;
  error: string | null;
  onCreateWorkflow: (name: string) => Promise<void>;
  onRenameWorkflow: (filename: string, name: string) => Promise<void>;
  onDeleteWorkflow: (filename: string) => Promise<void>;
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

function toWorkflowName(filename: string): string {
  return filename.replace(/\.json$/i, "");
}

export function WorkflowsCard({
  workflows,
  defaultFilename,
  status,
  error,
  onCreateWorkflow,
  onRenameWorkflow,
  onDeleteWorkflow,
}: WorkflowsCardProps) {
  const badge = getBadgeConfig(status);
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const selectedWorkflow = workflows.find((workflow) => workflow.filename === selectedFilename) ?? null;

  // Drop a selection whose file no longer exists (e.g. after a delete elsewhere).
  useEffect(() => {
    if (selectedFilename && !workflows.some((workflow) => workflow.filename === selectedFilename)) {
      setSelectedFilename(null);
      setPendingAction(null);
      setConfirmingDelete(false);
    }
  }, [workflows, selectedFilename]);

  function resetActions() {
    setPendingAction(null);
    setConfirmingDelete(false);
    setNameDraft("");
    setActionError(null);
  }

  function handleSelect(filename: string) {
    setSelectedFilename((current) => (current === filename ? null : filename));
    resetActions();
  }

  function handleStartCreate() {
    setPendingAction("create");
    setConfirmingDelete(false);
    setActionError(null);
    setNameDraft("");
  }

  function handleStartRename() {
    if (!selectedWorkflow) {
      return;
    }

    setPendingAction("rename");
    setConfirmingDelete(false);
    setActionError(null);
    setNameDraft(toWorkflowName(selectedWorkflow.filename));
  }

  async function handleSubmitName() {
    const trimmedName = nameDraft.trim();
    if (!trimmedName || isBusy) {
      return;
    }

    setIsBusy(true);
    setActionError(null);
    try {
      if (pendingAction === "create") {
        await onCreateWorkflow(trimmedName);
      } else if (pendingAction === "rename" && selectedWorkflow) {
        await onRenameWorkflow(selectedWorkflow.filename, trimmedName);
        setSelectedFilename(`${trimmedName}.json`);
      }
      resetActions();
    } catch (submitError) {
      setActionError(submitError instanceof Error ? submitError.message : "Could not save the workflow name.");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDelete() {
    if (!selectedWorkflow || isBusy) {
      return;
    }

    if (!confirmingDelete) {
      setConfirmingDelete(true);
      setPendingAction(null);
      setActionError(null);
      return;
    }

    setIsBusy(true);
    setActionError(null);
    try {
      await onDeleteWorkflow(selectedWorkflow.filename);
      setSelectedFilename(null);
      resetActions();
    } catch (deleteError) {
      setActionError(deleteError instanceof Error ? deleteError.message : "Could not delete the workflow.");
      setConfirmingDelete(false);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <Panel
      title="Workflows"
      subtitle="Saved workflows on this Raspberry Pi. Select one to rename or delete it."
      headerAction={<StatusBadge label={badge.label} tone={badge.tone} />}
    >
      <div className="workflows-card__links">
        <button
          className="workflow-editor__action workflow-editor__action--primary"
          disabled={isBusy}
          onClick={handleStartCreate}
          type="button"
        >
          Create new workflow
        </button>
        <button
          className="workflow-editor__action workflow-editor__action--ghost"
          disabled={!selectedWorkflow || isBusy}
          onClick={handleStartRename}
          type="button"
        >
          Edit name
        </button>
        <button
          className={confirmingDelete
            ? "workflow-editor__action workflow-editor__action--danger"
            : "workflow-editor__action workflow-editor__action--ghost"}
          disabled={!selectedWorkflow || isBusy}
          onClick={() => void handleDelete()}
          type="button"
        >
          {confirmingDelete ? "Confirm delete" : "Delete workflow"}
        </button>
        {confirmingDelete ? (
          <button
            className="workflow-editor__action workflow-editor__action--ghost"
            onClick={resetActions}
            type="button"
          >
            Cancel
          </button>
        ) : null}
      </div>

      {pendingAction ? (
        <div className="workflows-card__name-row">
          <input
            autoFocus
            onChange={(event) => setNameDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleSubmitName();
              } else if (event.key === "Escape") {
                resetActions();
              }
            }}
            placeholder={pendingAction === "create" ? "new-workflow-name" : "workflow-name"}
            type="text"
            value={nameDraft}
          />
          <button
            className="workflow-editor__action workflow-editor__action--primary"
            disabled={!nameDraft.trim() || isBusy}
            onClick={() => void handleSubmitName()}
            type="button"
          >
            {isBusy ? "Saving…" : pendingAction === "create" ? "Create" : "Rename"}
          </button>
          <button
            className="workflow-editor__action workflow-editor__action--ghost"
            onClick={resetActions}
            type="button"
          >
            Cancel
          </button>
        </div>
      ) : null}

      {actionError ? <p className="error-text">{actionError}</p> : null}
      {status === "error" ? <p className="error-text">{error ?? "Could not load the workflow list."}</p> : null}

      {status !== "error" && workflows.length === 0 ? (
        <p className="muted-text">No saved workflows yet. Use Create new workflow to add one.</p>
      ) : (
        <ul className="workflows-card__list">
          {workflows.map((workflow) => {
            const isSelected = workflow.filename === selectedFilename;
            return (
              <li key={workflow.path}>
                <button
                  aria-pressed={isSelected}
                  className={isSelected ? "workflows-card__row workflows-card__row--selected" : "workflows-card__row"}
                  onClick={() => handleSelect(workflow.filename)}
                  type="button"
                >
                  <span className="workflows-card__list-name">
                    <strong>{toWorkflowName(workflow.filename)}</strong>
                    {workflow.filename === defaultFilename ? <span className="workflows-card__active-tag">Active</span> : null}
                  </span>
                  <span className="muted-text">{formatUpdatedAt(workflow.updated_at)} - {formatFileSize(workflow.size_bytes)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

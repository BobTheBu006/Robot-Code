import { useEffect, useMemo, useState } from "react";

import {
  buildEsp32BoardFirmware,
  fetchEsp32Board,
  fetchEsp32Boards,
  flashEsp32BoardFirmware,
  saveEsp32BoardFile,
} from "../lib/api";
import type {
  Esp32BoardDetail,
  Esp32BoardSummary,
  Esp32FirmwareActionResponse,
} from "../types/esp32Builder";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

type RequestStatus = "loading" | "success" | "error";

export function Esp32FunctionBuilderCard() {
  const [boardsStatus, setBoardsStatus] = useState<RequestStatus>("loading");
  const [boardsError, setBoardsError] = useState<string | null>(null);
  const [boards, setBoards] = useState<Esp32BoardSummary[]>([]);
  const [selectedBoardId, setSelectedBoardId] = useState<string | null>(null);
  const [boardDetail, setBoardDetail] = useState<Esp32BoardDetail | null>(null);
  const [boardDetailStatus, setBoardDetailStatus] = useState<RequestStatus>("loading");
  const [boardDetailError, setBoardDetailError] = useState<string | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [firmwareActionState, setFirmwareActionState] = useState<"idle" | "running" | "success" | "error">("idle");
  const [firmwareActionLog, setFirmwareActionLog] = useState<string | null>(null);
  const [firmwareActionTitle, setFirmwareActionTitle] = useState<string | null>(null);

  async function loadBoards() {
    setBoardsStatus("loading");

    try {
      const response = await fetchEsp32Boards();
      setBoards(response.boards);
      setBoardsStatus("success");
      setBoardsError(null);

      if (!selectedBoardId && response.boards.length > 0) {
        setSelectedBoardId(response.boards[0].board_id);
      }

      if (
        selectedBoardId
        && !response.boards.some((board) => board.board_id === selectedBoardId)
      ) {
        setSelectedBoardId(response.boards[0]?.board_id ?? null);
      }
    } catch (error) {
      setBoardsStatus("error");
      setBoardsError(error instanceof Error ? error.message : "Could not load ESP32 boards.");
    }
  }

  useEffect(() => {
    void loadBoards();
  }, []);

  useEffect(() => {
    if (!selectedBoardId) {
      setBoardDetail(null);
      setBoardDetailStatus("success");
      return;
    }

    let cancelled = false;
    const boardId = selectedBoardId;

    async function loadBoardDetail() {
      setBoardDetailStatus("loading");

      try {
        const detail = await fetchEsp32Board(boardId);
        if (cancelled) {
          return;
        }

        setBoardDetail(detail);
        setBoardDetailStatus("success");
        setBoardDetailError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }

        setBoardDetailStatus("error");
        setBoardDetailError(error instanceof Error ? error.message : "Could not load board workspace.");
      }
    }

    void loadBoardDetail();

    return () => {
      cancelled = true;
    };
  }, [selectedBoardId]);

  useEffect(() => {
    if (!boardDetail) {
      setSelectedFilePath(null);
      setEditorContent("");
      return;
    }

    const preferredFile = boardDetail.files.find((file) => file.relative_path === "firmware/main.ino")
      ?? boardDetail.files[0]
      ?? null;

    if (!selectedFilePath || !boardDetail.files.some((file) => file.relative_path === selectedFilePath)) {
      setSelectedFilePath(preferredFile?.relative_path ?? null);
    }
  }, [boardDetail, selectedFilePath]);

  const selectedFile = useMemo(
    () => boardDetail?.files.find((file) => file.relative_path === selectedFilePath) ?? null,
    [boardDetail, selectedFilePath],
  );

  useEffect(() => {
    setEditorContent(selectedFile?.content ?? "");
    setSaveState("idle");
    setSaveMessage(null);
  }, [selectedFilePath, selectedFile?.content]);

  async function handleSave() {
    if (!selectedBoardId || !selectedFilePath) {
      return;
    }

    setSaveState("saving");
    try {
      const response = await saveEsp32BoardFile(selectedBoardId, selectedFilePath, editorContent);
      setSaveState("saved");
      setSaveMessage(`Saved ${response.relative_path}`);

      setBoardDetail((currentDetail) => {
        if (!currentDetail) {
          return currentDetail;
        }

        return {
          ...currentDetail,
          files: currentDetail.files.map((file) =>
            file.relative_path === selectedFilePath
              ? {
                  ...file,
                  content: editorContent,
                  size_bytes: editorContent.length,
                }
              : file),
        };
      });

      const refreshedDetail = await fetchEsp32Board(selectedBoardId);
      setBoardDetail(refreshedDetail);
      await loadBoards();
    } catch (error) {
      setSaveState("error");
      setSaveMessage(error instanceof Error ? error.message : "Could not save file.");
    }
  }

  async function handleFirmwareAction(action: "build" | "flash") {
    if (!selectedBoardId) {
      return;
    }

    setFirmwareActionState("running");
    setFirmwareActionTitle(action === "build" ? "Build log" : "Flash log");
    setFirmwareActionLog(null);

    try {
      const response: Esp32FirmwareActionResponse = action === "build"
        ? await buildEsp32BoardFirmware(selectedBoardId)
        : await flashEsp32BoardFirmware(selectedBoardId);

      setFirmwareActionState(response.ok ? "success" : "error");
      setFirmwareActionLog([
        `Action: ${response.action}`,
        `Board: ${response.board_id}`,
        `FQBN: ${response.fqbn}`,
        response.port ? `Port: ${response.port}` : null,
        `Sketch: ${response.sketch_entry_file}`,
        response.auto_reset_attempted ? `Auto reset: attempted` : null,
        `Auto reset note: ${response.auto_reset_note}`,
        "",
        "$ " + response.command.join(" "),
        "",
        response.log,
      ].filter(Boolean).join("\n"));
    } catch (error) {
      setFirmwareActionState("error");
      setFirmwareActionLog(error instanceof Error ? error.message : `Could not ${action} firmware.`);
    }
  }

  const selectedBoard = boards.find((board) => board.board_id === selectedBoardId) ?? null;
  const isDirty = selectedFile ? editorContent !== selectedFile.content : false;

  return (
    <Panel
      title="Function Builder"
      subtitle="Edit the ESP32 firmware workspace tied to connected boards, then build and flash it from the Pi. Workflow-block blueprints in this workspace drive the robot action blocks under the canvas."
      headerAction={(
        <div className="function-builder__header-actions">
          <button className="workflow-editor__action" onClick={() => void loadBoards()} type="button">
            Refresh boards
          </button>
          <button
            className="workflow-editor__action workflow-editor__action--primary"
            disabled={!selectedBoardId || !selectedFilePath || saveState === "saving" || !isDirty}
            onClick={() => void handleSave()}
            type="button"
          >
            {saveState === "saving" ? "Saving..." : "Save file"}
          </button>
        </div>
      )}
    >
      <div className="function-builder">
        <aside className="function-builder__sidebar">
          <div className="function-builder__sidebar-section">
            <div className="function-builder__section-header">
              <strong>Connected boards</strong>
              <span>{boards.length}</span>
            </div>

            {boardsStatus === "loading" ? <p>Loading ESP32 boards...</p> : null}
            {boardsStatus === "error" ? <p className="error-text">{boardsError}</p> : null}
            {boardsStatus === "success" && boards.length === 0 ? (
              <p>No ESP32 serial boards are connected right now.</p>
            ) : null}

            <div className="function-builder__board-list">
              {boards.map((board) => (
                <button
                  className={board.board_id === selectedBoardId
                    ? "function-builder__board function-builder__board--active"
                    : "function-builder__board"}
                  key={board.board_id}
                  onClick={() => setSelectedBoardId(board.board_id)}
                  type="button"
                >
                  <div>
                    <strong>{board.display_name}</strong>
                    <span>{board.port ?? board.workspace_path}</span>
                  </div>
                  <StatusBadge
                    label={board.connected ? "Connected" : "Offline"}
                    tone={board.connected ? "online" : "neutral"}
                  />
                </button>
              ))}
            </div>
          </div>

          <div className="function-builder__sidebar-section">
            <div className="function-builder__section-header">
              <strong>Workspace files</strong>
              <span>{boardDetail?.files.length ?? 0}</span>
            </div>
            <div className="function-builder__file-list">
              {(boardDetail?.files ?? []).map((file) => (
                <button
                  className={file.relative_path === selectedFilePath
                    ? "function-builder__file function-builder__file--active"
                    : "function-builder__file"}
                  key={file.relative_path}
                  onClick={() => setSelectedFilePath(file.relative_path)}
                  type="button"
                >
                  <strong>{file.relative_path}</strong>
                  <span>{file.language}</span>
                </button>
              ))}
            </div>
          </div>
        </aside>

        <div className="function-builder__main">
          <div className="function-builder__meta">
            <div className="function-builder__meta-card">
              <span>Selected board</span>
              <strong>{selectedBoard?.display_name ?? "No board selected"}</strong>
              <small>{selectedBoard?.workspace_path ?? "Waiting for board selection"}</small>
            </div>
            <div className="function-builder__meta-card">
              <span>Port</span>
              <strong>{selectedBoard?.port ?? "Not connected"}</strong>
              <small>{selectedBoard?.description ?? "Local firmware workspace only"}</small>
            </div>
            <div className="function-builder__meta-card">
              <span>Generated blocks</span>
              <strong>{selectedBoard?.generated_function_ids.join(", ") || "None yet"}</strong>
              <small>The workflow editor reads these through the normal function discovery path.</small>
            </div>
            <div className="function-builder__meta-card">
              <span>Firmware target</span>
              <strong>{boardDetail?.fqbn ?? boardDetail?.toolchain?.fqbn_default ?? "Unknown"}</strong>
              <small>{boardDetail?.firmware_entry_file ?? "No firmware entry file configured"}</small>
            </div>
          </div>

          <div className="function-builder__flash-actions">
            <button
              className="workflow-editor__action"
              disabled={!selectedBoardId || firmwareActionState === "running"}
              onClick={() => void handleFirmwareAction("build")}
              type="button"
            >
              {firmwareActionState === "running" && firmwareActionTitle === "Build log" ? "Building..." : "Build firmware"}
            </button>
            <button
              className="workflow-editor__action workflow-editor__action--primary"
              disabled={!selectedBoardId || firmwareActionState === "running"}
              onClick={() => void handleFirmwareAction("flash")}
              type="button"
            >
              {firmwareActionState === "running" && firmwareActionTitle === "Flash log" ? "Flashing..." : "Build + Flash"}
            </button>
          </div>

          <div className="function-builder__toolchain">
            <div className="function-builder__section-header">
              <strong>Toolchain</strong>
              <StatusBadge
                label={boardDetail?.toolchain?.arduino_cli_available ? "Ready" : "Missing"}
                tone={boardDetail?.toolchain?.arduino_cli_available ? "online" : "offline"}
              />
            </div>
            <p>
              {boardDetail?.toolchain?.arduino_cli_available
                ? `arduino-cli: ${boardDetail.toolchain.arduino_cli_path}`
                : "arduino-cli is not installed on this Pi yet, so build and flash will fail until the toolchain is installed."}
            </p>
            <p>{boardDetail?.toolchain?.auto_reset_note}</p>
            {boardDetail?.toolchain?.config_file ? (
              <p>Config: {boardDetail.toolchain.config_file}</p>
            ) : null}
          </div>

          <div className="function-builder__editor-card">
            <div className="function-builder__editor-header">
              <div>
                <strong>{selectedFile?.relative_path ?? "Select a workspace file"}</strong>
                <span>{selectedFile?.absolute_path ?? "No file selected"}</span>
              </div>
              <div className="function-builder__editor-status">
                {isDirty ? <span>Unsaved changes</span> : <span>Saved</span>}
                {saveMessage ? <small>{saveMessage}</small> : null}
              </div>
            </div>

            {boardDetailStatus === "loading" ? <p>Loading workspace...</p> : null}
            {boardDetailStatus === "error" ? <p className="error-text">{boardDetailError}</p> : null}

            <textarea
              className="function-builder__editor"
              onChange={(event) => setEditorContent(event.target.value)}
              spellCheck={false}
              value={editorContent}
            />
          </div>

          {firmwareActionLog ? (
            <div className="function-builder__editor-card">
              <div className="function-builder__editor-header">
                <div>
                  <strong>{firmwareActionTitle ?? "Firmware log"}</strong>
                  <span>{firmwareActionState === "error" ? "Last action failed" : "Latest tool output from the Pi"}</span>
                </div>
              </div>
              <pre className="function-builder__log">{firmwareActionLog}</pre>
            </div>
          ) : null}

          <div className="function-builder__schema-grid">
            {(boardDetail?.blueprints ?? []).map((blueprint) => (
              <section className="function-builder__schema-card" key={blueprint.manifest.id}>
                <div className="function-builder__schema-header">
                  <div>
                    <strong>{blueprint.manifest.display_name}</strong>
                    <p>{blueprint.manifest.description}</p>
                  </div>
                  <StatusBadge label={blueprint.protocol} tone="neutral" />
                </div>

                <div className="function-builder__schema-columns">
                  <div>
                    <h3>Basic block inputs</h3>
                    <ul className="function-builder__schema-list">
                      {blueprint.manifest.inputs.map((input) => (
                        <li key={input.key}>
                          <strong>{input.label}</strong>
                          <span>{input.type}</span>
                          <p>{input.description ?? "No description provided."}</p>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <h3>Advanced builder inputs</h3>
                    <ul className="function-builder__schema-list">
                      {blueprint.advanced_builder_inputs.map((input) => (
                        <li key={input.key}>
                          <strong>{input.label}</strong>
                          <span>{input.type}</span>
                          <p>{input.description ?? "No description provided."}</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="function-builder__schema-footer">
                  <span>Firmware entry: {blueprint.firmware_entry_file}</span>
                  {blueprint.notes ? <span>{blueprint.notes}</span> : null}
                </div>
              </section>
            ))}
          </div>

          {boardDetail?.errors.length ? (
            <div className="function-builder__warnings">
              <strong>Workspace warnings</strong>
              <ul>
                {boardDetail.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}

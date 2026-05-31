import type { DragEvent } from "react";
import { useEffect, useState } from "react";

import { WORKFLOW_BLOCK_MIME } from "../../lib/workflow";
import type { WorkflowBlockDefinition } from "../../types/workflow";

interface WorkflowPaletteProps {
  blocks: WorkflowBlockDefinition[];
  discoveryErrors: string[];
  onDeleteCustomBlock: (block: WorkflowBlockDefinition) => void;
}

const LOGIC_BLOCK_IDS = new Set(["if", "if_else", "while", "for", "loop_over"]);
const CATEGORY_ORDER = ["Basic Functions", "Logic Functions", "Advanced Functions", "Compound Functions"];

function getPaletteCategory(block: WorkflowBlockDefinition): string {
  if (LOGIC_BLOCK_IDS.has(block.id)) {
    return "Logic Functions";
  }

  if (block.category === "Basic Blocks") {
    return "Basic Functions";
  }

  return block.category;
}

function getOrderedCategoryEntries(
  groups: Record<string, WorkflowBlockDefinition[]>,
): Array<[string, WorkflowBlockDefinition[]]> {
  return Object.entries(groups).sort(([categoryA], [categoryB]) => {
    const indexA = CATEGORY_ORDER.indexOf(categoryA);
    const indexB = CATEGORY_ORDER.indexOf(categoryB);

    if (indexA !== -1 || indexB !== -1) {
      return (indexA === -1 ? CATEGORY_ORDER.length : indexA) - (indexB === -1 ? CATEGORY_ORDER.length : indexB);
    }

    return categoryA.localeCompare(categoryB);
  });
}

function scrollPageNearViewportEdge(clientY: number) {
  const edgeSize = 86;
  const maxScrollStep = 10;
  const minScrollStep = 3;
  const canvasTop = document.querySelector<HTMLElement>(".workflow-editor__canvas-shell")?.getBoundingClientRect().top;
  const canvasTopScrollY = canvasTop === undefined ? 0 : Math.max(0, window.scrollY + canvasTop);

  function getScrollStep(distanceIntoEdge: number) {
    const intensity = Math.max(0, Math.min(1, distanceIntoEdge / edgeSize));
    return Math.round(minScrollStep + (maxScrollStep - minScrollStep) * intensity);
  }

  if (clientY < edgeSize) {
    if (window.scrollY <= canvasTopScrollY + 1) {
      return;
    }

    const nextScrollY = Math.max(canvasTopScrollY, window.scrollY - getScrollStep(edgeSize - clientY));
    window.scrollTo({ top: nextScrollY });
    return;
  }

  if (clientY > window.innerHeight - edgeSize) {
    window.scrollBy({ top: getScrollStep(clientY - (window.innerHeight - edgeSize)) });
  }
}

export function WorkflowPalette({ blocks, discoveryErrors, onDeleteCustomBlock }: WorkflowPaletteProps) {
  const [hiddenBlockIds, setHiddenBlockIds] = useState<Set<string>>(() => new Set());
  const [showAllBlocks, setShowAllBlocks] = useState(false);
  const [draggingBlockId, setDraggingBlockId] = useState<string | null>(null);
  const visibleBlocks = showAllBlocks ? blocks : blocks.filter((block) => !hiddenBlockIds.has(block.id));
  const hiddenBlocks = blocks.filter((block) => hiddenBlockIds.has(block.id));
  const hiddenBlockCount = hiddenBlocks.length;
  const groupedBlocks = visibleBlocks.reduce<Record<string, WorkflowBlockDefinition[]>>((groups, block) => {
    const category = getPaletteCategory(block);
    groups[category] = [...(groups[category] ?? []), block];
    return groups;
  }, {});
  const groupedBlockEntries = getOrderedCategoryEntries(groupedBlocks);

  useEffect(() => {
    if (!draggingBlockId) {
      return undefined;
    }

    function handleWindowDragOver(event: globalThis.DragEvent) {
      scrollPageNearViewportEdge(event.clientY);
    }

    function clearDragState() {
      setDraggingBlockId(null);
    }

    window.addEventListener("dragover", handleWindowDragOver);
    window.addEventListener("drop", clearDragState);
    window.addEventListener("dragend", clearDragState);

    return () => {
      window.removeEventListener("dragover", handleWindowDragOver);
      window.removeEventListener("drop", clearDragState);
      window.removeEventListener("dragend", clearDragState);
    };
  }, [draggingBlockId]);

  function handleDragStart(event: DragEvent<HTMLDivElement>, block: WorkflowBlockDefinition) {
    event.dataTransfer.setData(WORKFLOW_BLOCK_MIME, JSON.stringify(block));
    event.dataTransfer.effectAllowed = "copy";
    setDraggingBlockId(block.id);
  }

  function handleHideBlock(blockId: string) {
    setHiddenBlockIds((currentIds) => {
      const nextIds = new Set(currentIds);
      nextIds.add(blockId);
      return nextIds;
    });
  }

  function handleShowAllBlocks() {
    setShowAllBlocks(true);
  }

  function handleUnhideBlock(blockId: string) {
    setHiddenBlockIds((currentIds) => {
      const nextIds = new Set(currentIds);
      nextIds.delete(blockId);
      return nextIds;
    });
  }

  return (
    <section className="workflow-palette">
      <div className="workflow-palette__header">
        <div>
          <h3>Blocks</h3>
          <p>Drag a block onto the canvas to add it to the workflow.</p>
        </div>
        <button
          className="workflow-palette__toggle"
          disabled={hiddenBlockCount === 0}
          onClick={handleShowAllBlocks}
          type="button"
        >
          {hiddenBlockCount > 0 && !showAllBlocks ? `Show all (${hiddenBlockCount})` : "All shown"}
        </button>
      </div>

      {visibleBlocks.length > 0 ? (
        <>
          <div className="workflow-palette__scroll">
            {groupedBlockEntries.map(([category, categoryBlocks]) => (
              <section className="workflow-palette__group" key={category}>
                <h4>{category}</h4>
                <div className="workflow-palette__list">
                  {categoryBlocks.map((block) => {
                    const blockIsHidden = hiddenBlockIds.has(block.id);
                    const canDeleteCustomBlock = (block.kind === "advanced" || block.kind === "robot-action") && block.builderBoardId && block.builderBaseFunctionId;

                    return (
                      <div className="workflow-palette__item-shell" key={block.id}>
                        <div
                          className={`workflow-palette__item${blockIsHidden ? " workflow-palette__item--hidden" : ""}`}
                          draggable
                          onDragEnd={() => setDraggingBlockId(null)}
                          onDragStart={(event) => handleDragStart(event, block)}
                        >
                          <button
                            className={`workflow-palette__hide${blockIsHidden ? " workflow-palette__hide--unhide" : ""}`}
                            onClick={() => blockIsHidden ? handleUnhideBlock(block.id) : handleHideBlock(block.id)}
                            title={blockIsHidden ? `Unhide ${block.displayName}` : `Hide ${block.displayName} from the block list`}
                            type="button"
                          >
                            {blockIsHidden ? "Unhide" : "Hide"}
                          </button>
                          <strong>{block.displayName}</strong>
                          <span>{block.description}</span>

                          {canDeleteCustomBlock ? (
                            <div className="workflow-palette__item-actions">
                              <button
                                className="workflow-palette__delete"
                                onClick={() => onDeleteCustomBlock(block)}
                                title={`Delete custom block ${block.displayName}`}
                                type="button"
                              >
                                Delete
                              </button>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>

          {discoveryErrors.length > 0 ? (
            <section className="workflow-palette__issues">
              <h4>Discovery Issues</h4>
              <ul>
                {discoveryErrors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : (
        <p className="workflow-palette__empty">All blocks are hidden. Use Show all to show them again, then press Unhide on the ones you want to keep visible.</p>
      )}
    </section>
  );
}

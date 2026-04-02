import type { DragEvent } from "react";

import { WORKFLOW_BLOCK_MIME } from "../../lib/workflow";
import type { WorkflowBlockDefinition } from "../../types/workflow";

interface WorkflowPaletteProps {
  blocks: WorkflowBlockDefinition[];
  discoveryErrors: string[];
  onDeleteCustomBlock: (block: WorkflowBlockDefinition) => void;
}

export function WorkflowPalette({ blocks, discoveryErrors, onDeleteCustomBlock }: WorkflowPaletteProps) {
  const groupedBlocks = blocks.reduce<Record<string, WorkflowBlockDefinition[]>>((groups, block) => {
    groups[block.category] = [...(groups[block.category] ?? []), block];
    return groups;
  }, {});

  function handleDragStart(event: DragEvent<HTMLButtonElement>, block: WorkflowBlockDefinition) {
    event.dataTransfer.setData(WORKFLOW_BLOCK_MIME, JSON.stringify(block));
    event.dataTransfer.effectAllowed = "copy";
  }

  return (
    <section className="workflow-palette">
      <div className="workflow-palette__header">
        <h3>Blocks</h3>
        <p>Drag a block onto the canvas to add it to the workflow.</p>
      </div>

      <div className="workflow-palette__scroll">
        {Object.entries(groupedBlocks).map(([category, categoryBlocks]) => (
          <section className="workflow-palette__group" key={category}>
            <h4>{category}</h4>
            <div className="workflow-palette__list">
              {categoryBlocks.map((block) => (
                <div className="workflow-palette__item-shell" key={block.id}>
                  <button
                    className="workflow-palette__item"
                    draggable
                    onDragStart={(event) => handleDragStart(event, block)}
                    type="button"
                  >
                    <strong>{block.displayName}</strong>
                    <span>{block.description}</span>
                  </button>

                  {block.kind === "robot-action" && block.builderBoardId && block.builderBaseFunctionId ? (
                    <button
                      className="workflow-palette__delete"
                      onClick={() => onDeleteCustomBlock(block)}
                      title={`Delete custom block ${block.displayName}`}
                      type="button"
                    >
                      Delete
                    </button>
                  ) : null}
                </div>
              ))}
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
    </section>
  );
}

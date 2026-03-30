import { Panel } from "./Panel";

interface PlaceholderPanelProps {
  title: string;
  description: string;
}

export function PlaceholderPanel({ title, description }: PlaceholderPanelProps) {
  return (
    <Panel title={title}>
      <div className="placeholder-box">
        <p>{description}</p>
      </div>
    </Panel>
  );
}

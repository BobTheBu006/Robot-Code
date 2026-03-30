import type { PropsWithChildren, ReactNode } from "react";

interface PanelProps extends PropsWithChildren {
  title: string;
  subtitle?: string;
  headerAction?: ReactNode;
}

export function Panel({ title, subtitle, headerAction, children }: PanelProps) {
  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {headerAction ? <div>{headerAction}</div> : null}
      </div>
      <div className="panel__body">{children}</div>
    </section>
  );
}

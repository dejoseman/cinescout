import type { ReactNode } from "react";

export default function Topbar({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="topbar">
      <span className="topbar-title">{title}</span>
      {subtitle && <span className="topbar-sub">{subtitle}</span>}
      <span className="spacer" />
      {actions}
    </header>
  );
}

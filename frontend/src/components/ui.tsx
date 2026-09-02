/** Shared presentational primitives. Colour here is semantic, never decorative. */

import type { ReactNode } from "react";
import type {
  Confidence,
  Severity,
  TaskStatus,
  VerificationStatus,
} from "../lib/types";

/* -------------------------------------------------------------------------
   Badges
   ------------------------------------------------------------------------- */

const SEVERITY_CLASS: Record<Severity, string> = {
  CRITICAL: "badge-critical",
  HIGH: "badge-high",
  MEDIUM: "badge-medium",
  LOW: "badge-low",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge ${SEVERITY_CLASS[severity] ?? "badge-neutral"}`}>
      <span className="pip" />
      {severity}
    </span>
  );
}

const VERIFICATION_CLASS: Record<VerificationStatus, string> = {
  VERIFIED: "badge-verified",
  SUPPORTED: "badge-low",
  CONFLICTING: "badge-conflict",
  UNCONFIRMED: "badge-medium",
  INSUFFICIENT_EVIDENCE: "badge-neutral",
};

const VERIFICATION_LABEL: Record<VerificationStatus, string> = {
  VERIFIED: "Verified",
  SUPPORTED: "Supported",
  CONFLICTING: "Conflicting",
  UNCONFIRMED: "Unconfirmed",
  INSUFFICIENT_EVIDENCE: "Insufficient",
};

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  return (
    <span className={`badge ${VERIFICATION_CLASS[status] ?? "badge-neutral"}`}>
      <span className="pip" />
      {VERIFICATION_LABEL[status] ?? status}
    </span>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const tone =
    confidence === "HIGH" ? "badge-verified" : confidence === "MEDIUM" ? "badge-low" : "badge-neutral";
  return <span className={`badge ${tone}`}>{confidence} confidence</span>;
}

const TASK_CLASS: Record<TaskStatus, string> = {
  PENDING: "badge-neutral",
  RUNNING: "badge-accent",
  OK: "badge-verified",
  EMPTY: "badge-medium",
  FAILED: "badge-critical",
};

export function TaskBadge({ status }: { status: TaskStatus }) {
  return <span className={`badge ${TASK_CLASS[status] ?? "badge-neutral"}`}>{status}</span>;
}

export function CategoryTag({ category }: { category: string }) {
  return <span className="badge badge-neutral">{category.replace(/_/g, " ")}</span>;
}

/* -------------------------------------------------------------------------
   Score visualisation
   ------------------------------------------------------------------------- */

/** Colour by band, so the ring itself communicates the verdict. */
function scoreColour(score: number): string {
  if (score >= 75) return "var(--verified)";
  if (score >= 50) return "var(--medium)";
  if (score >= 30) return "var(--high)";
  return "var(--critical)";
}

export function ScoreRing({
  score,
  label,
  size = 132,
}: {
  score: number;
  label: string;
  size?: number;
}) {
  const stroke = 9;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.max(0, Math.min(100, score)) / 100);

  return (
    <div className="ring-wrap" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle
          className="ring-track"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
        />
        <circle
          className="ring-fill"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          stroke={scoreColour(score)}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="ring-value">
        <span className="ring-number">{score}</span>
        <span className="ring-unit">{label}</span>
      </div>
    </div>
  );
}

export function Metric({
  value,
  label,
  tone,
}: {
  value: ReactNode;
  label: string;
  tone?: string;
}) {
  return (
    <div className="metric">
      <div className="metric-value" style={tone ? { color: tone } : undefined}>
        {value}
      </div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

export function Bar({ value, max, colour }: { value: number; max: number; colour?: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="bar">
      <div
        className="bar-fill"
        style={{ width: `${pct}%`, background: colour ?? "var(--accent)" }}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------
   Layout helpers
   ------------------------------------------------------------------------- */

export function Card({
  title,
  action,
  children,
  eyebrow,
}: {
  title?: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || action) && (
        <header className="card-head">
          <div>
            {eyebrow && <div className="eyebrow">{eyebrow}</div>}
            {title && <h3 className="card-title">{title}</h3>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <div style={{ fontWeight: 600, color: "var(--text-2)", marginBottom: 5 }}>{title}</div>
      {hint && <div style={{ fontSize: 12.5 }}>{hint}</div>}
    </div>
  );
}

export function Callout({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "error";
  children: ReactNode;
}) {
  return <div className={`callout callout-${tone}`}>{children}</div>;
}

export function SourceLink({ url, children }: { url: string; children: ReactNode }) {
  return (
    <a className="source-link" href={url} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  );
}

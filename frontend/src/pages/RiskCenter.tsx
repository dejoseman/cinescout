import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import Topbar from "../components/Topbar";
import { Callout, Card, Empty, Metric, SeverityBadge } from "../components/ui";
import type { Severity } from "../lib/types";
import { sourceIndex, useProject } from "../lib/useProject";

const ORDER: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export default function RiskCenter() {
  const { id } = useParams();
  const { project, error, loading } = useProject(id);
  const [filter, setFilter] = useState<Severity | "ALL">("ALL");

  const sources = useMemo(() => sourceIndex(project), [project]);

  const evidenceById = useMemo(() => {
    const index = new Map<string, NonNullable<typeof project>["evidence"][number]>();
    project?.evidence.forEach((item) => index.set(item.id, item));
    return index;
  }, [project]);

  if (loading) {
    return (
      <>
        <Topbar title="Risk center" />
        <div className="content">
          <div className="row dim" style={{ padding: 30 }}>
            <span className="spinner" />
            <span style={{ marginLeft: 9 }}>Loading risks…</span>
          </div>
        </div>
      </>
    );
  }

  if (error || !project) {
    return (
      <>
        <Topbar title="Risk center" />
        <div className="content">
          <Callout tone="error">{error ?? "Project not found."}</Callout>
        </div>
      </>
    );
  }

  const counts = ORDER.reduce<Record<string, number>>((acc, severity) => {
    acc[severity] = project.risks.filter((risk) => risk.severity === severity).length;
    return acc;
  }, {});

  const visible =
    filter === "ALL" ? project.risks : project.risks.filter((risk) => risk.severity === filter);

  const needsConfirmation = project.risks.filter((risk) => risk.requires_human_confirmation);

  return (
    <>
      <Topbar
        title="Risk center"
        subtitle={`${project.risks.length} risks · ${project.gaps.length} research gaps`}
      />

      <div className="content wide stack">
        <div className="grid grid-4">
          <Metric
            value={counts.CRITICAL ?? 0}
            label="Critical"
            tone={counts.CRITICAL ? "var(--critical)" : "var(--verified)"}
          />
          <Metric
            value={counts.HIGH ?? 0}
            label="High"
            tone={counts.HIGH ? "var(--high)" : undefined}
          />
          <Metric value={counts.MEDIUM ?? 0} label="Medium" />
          <Metric
            value={needsConfirmation.length}
            label="Need human confirmation"
            tone={needsConfirmation.length ? "var(--medium)" : undefined}
          />
        </div>

        {needsConfirmation.length > 0 && (
          <Callout tone="warn">
            <strong>{needsConfirmation.length} findings require human confirmation.</strong>{" "}
            CineScout researches public sources; it does not give legal advice. Permit,
            regulatory, insurance and safety matters must be confirmed with the relevant
            authority or a qualified professional before you commit budget or crew.
          </Callout>
        )}

        <Card>
          <div className="filter-bar">
            <button
              className={`filter-chip ${filter === "ALL" ? "active" : ""}`}
              onClick={() => setFilter("ALL")}
            >
              All ({project.risks.length})
            </button>
            {ORDER.map((severity) => (
              <button
                key={severity}
                className={`filter-chip ${filter === severity ? "active" : ""}`}
                onClick={() => setFilter(severity)}
              >
                {severity} ({counts[severity] ?? 0})
              </button>
            ))}
          </div>
        </Card>

        {visible.length === 0 ? (
          <Empty
            title={project.risks.length === 0 ? "No risks were identified" : "No risks at this severity"}
            hint={
              project.risks.length === 0
                ? "This is only meaningful if the research itself succeeded — check the report's coverage score."
                : undefined
            }
          />
        ) : (
          <div className="stack-sm">
            {visible.map((risk) => (
              <article className={`risk-card ${risk.severity.toLowerCase()}`} key={risk.id}>
                <div className="row-between" style={{ marginBottom: 9 }}>
                  <div className="row" style={{ gap: 9, minWidth: 0 }}>
                    <span className="mono dim">{risk.id}</span>
                    <h3 style={{ fontSize: 14 }}>{risk.title}</h3>
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    <span className="badge badge-neutral">
                      {risk.category.replace(/_/g, " ")}
                    </span>
                    <SeverityBadge severity={risk.severity} />
                  </div>
                </div>

                <p className="muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
                  {risk.reasoning}
                </p>

                <div
                  style={{
                    marginTop: 13,
                    paddingTop: 13,
                    borderTop: "1px solid var(--border)",
                  }}
                >
                  <div className="eyebrow" style={{ marginBottom: 5 }}>
                    Recommended action
                  </div>
                  <p style={{ fontSize: 13, lineHeight: 1.55 }}>{risk.recommended_action}</p>
                </div>

                {risk.evidence_ids.length > 0 && (
                  <div style={{ marginTop: 13 }}>
                    <div className="eyebrow" style={{ marginBottom: 6 }}>
                      Supporting evidence
                    </div>
                    <div className="stack-sm">
                      {risk.evidence_ids.map((evidenceId) => {
                        const evidence = evidenceById.get(evidenceId);
                        if (!evidence) return null;
                        const source = sources.get(evidence.source_id);
                        return (
                          <div
                            key={evidenceId}
                            className="row"
                            style={{ gap: 8, alignItems: "flex-start" }}
                          >
                            <span className="badge badge-accent mono">{evidence.source_id}</span>
                            <div className="col" style={{ minWidth: 0 }}>
                              <span style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                                {evidence.claim}
                              </span>
                              {source && <span className="dim mono">{source.domain}</span>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {risk.requires_human_confirmation && (
                  <div style={{ marginTop: 12 }}>
                    <span className="badge badge-medium">
                      Requires confirmation with the relevant authority
                    </span>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}

        {/* Research gaps ----------------------------------------------------- */}
        <Card
          title="Research gaps"
          eyebrow="What the research could not answer"
          action={
            <span className="dim" style={{ fontSize: 12 }}>
              {project.gaps.length} open
            </span>
          }
        >
          {project.gaps.length === 0 ? (
            <p className="dim" style={{ fontSize: 13 }}>
              No unresolved research gaps were recorded.
            </p>
          ) : (
            <div className="stack-sm">
              {project.gaps.map((gap) => (
                <div
                  key={gap.id}
                  style={{
                    padding: "11px 0",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                    {gap.question}
                  </div>
                  <div className="dim" style={{ fontSize: 12, lineHeight: 1.55 }}>
                    {gap.why_it_matters}
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <span className="badge badge-neutral">Ask: {gap.suggested_source}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Failed research tasks ---------------------------------------------- */}
        {project.search_results.some((r) => r.status === "FAILED" || r.status === "EMPTY") && (
          <Card title="Research tasks that did not return usable results" eyebrow="Transparency">
            <div className="stack-sm">
              {project.search_results
                .filter((r) => r.status === "FAILED" || r.status === "EMPTY")
                .map((result) => (
                  <div className="row-between" key={result.task_id} style={{ fontSize: 12.5 }}>
                    <div className="col" style={{ minWidth: 0 }}>
                      <span>{result.question || result.task_id}</span>
                      {result.error && (
                        <span className="dim mono">{result.error}</span>
                      )}
                    </div>
                    <span
                      className={`badge ${result.status === "FAILED" ? "badge-critical" : "badge-medium"}`}
                    >
                      {result.status}
                    </span>
                  </div>
                ))}
            </div>
            <p className="dim" style={{ fontSize: 11.5, marginTop: 11, lineHeight: 1.55 }}>
              These tasks reduced the research coverage component of the readiness score.
              They are shown rather than hidden, because a gap you know about is safer than
              one you do not.
            </p>
          </Card>
        )}
      </div>
    </>
  );
}

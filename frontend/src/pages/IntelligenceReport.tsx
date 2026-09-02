import { Link, useParams } from "react-router-dom";

import Topbar from "../components/Topbar";
import {
  Bar,
  Callout,
  Card,
  Empty,
  Metric,
  ScoreRing,
  SeverityBadge,
} from "../components/ui";
import { useProject } from "../lib/useProject";

export default function IntelligenceReport() {
  const { id } = useParams();
  const { project, error, loading } = useProject(id);

  if (loading) {
    return (
      <>
        <Topbar title="Intelligence report" />
        <div className="content">
          <div className="row dim" style={{ padding: 30 }}>
            <span className="spinner" />
            <span style={{ marginLeft: 9 }}>Loading report…</span>
          </div>
        </div>
      </>
    );
  }

  if (error || !project) {
    return (
      <>
        <Topbar title="Intelligence report" />
        <div className="content">
          <Callout tone="error">{error ?? "Project not found."}</Callout>
        </div>
      </>
    );
  }

  const { assessment, report, brief } = project;

  if (project.status === "RUNNING" || project.status === "QUEUED") {
    return (
      <>
        <Topbar title={brief.title} subtitle="Analysis in progress" />
        <div className="content">
          <Card title="Analysis still running" eyebrow={brief.title}>
            <p className="muted" style={{ marginBottom: 14 }}>
              This production is still being researched.
            </p>
            <Link className="btn btn-primary btn-sm" to={`/projects/${id}/live`}>
              Watch live research
            </Link>
          </Card>
        </div>
      </>
    );
  }

  if (project.status === "FAILED") {
    return (
      <>
        <Topbar title={brief.title} subtitle="Analysis failed" />
        <div className="content stack">
          <Callout tone="error">
            <strong>This analysis did not complete.</strong>
            <div style={{ marginTop: 5 }}>{project.error}</div>
          </Callout>
          <Callout tone="info">
            No report is shown because CineScout will not present model output as research
            findings. Re-run the analysis once the underlying problem is resolved.
          </Callout>
        </div>
      </>
    );
  }

  const topRisks = [...project.risks]
    .filter((risk) => risk.severity === "CRITICAL" || risk.severity === "HIGH")
    .slice(0, 4);

  return (
    <>
      <Topbar
        title={brief.title}
        subtitle={[brief.city, brief.country].filter(Boolean).join(", ")}
        actions={
          <div className="row" style={{ gap: 6 }}>
            <Link className="btn btn-sm" to={`/projects/${id}/evidence`}>
              Evidence
            </Link>
            <Link className="btn btn-sm" to={`/projects/${id}/risks`}>
              Risks
            </Link>
          </div>
        }
      />

      <div className="content wide stack">
        {project.warnings.length > 0 && (
          <Callout tone="warn">
            <strong>Limitations of this run</strong>
            <ul className="list-clean" style={{ marginTop: 7, color: "inherit" }}>
              {project.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          </Callout>
        )}

        {/* Headline assessment ------------------------------------------- */}
        {assessment && (
          <div
            className="grid"
            style={{ gridTemplateColumns: "auto 1fr", alignItems: "center", gap: 26 }}
          >
            <Card>
              <div className="row" style={{ gap: 26 }}>
                <ScoreRing score={assessment.readiness_score} label="READINESS" />
                <ScoreRing score={assessment.evidence_confidence} label="CONFIDENCE" size={112} />
              </div>
            </Card>

            <div className="grid grid-3" style={{ gap: 12 }}>
              <Metric
                value={assessment.critical_risks}
                label="Critical risks"
                tone={assessment.critical_risks > 0 ? "var(--critical)" : "var(--verified)"}
              />
              <Metric
                value={assessment.high_risks}
                label="High risks"
                tone={assessment.high_risks > 0 ? "var(--high)" : undefined}
              />
              <Metric value={assessment.research_gaps} label="Research gaps" />
              <Metric value={assessment.total_sources} label="Sources" />
              <Metric value={assessment.total_evidence} label="Claims" />
              <Metric
                value={assessment.conflicting_findings}
                label="Conflicts found"
                tone={assessment.conflicting_findings > 0 ? "var(--conflict)" : undefined}
              />
            </div>
          </div>
        )}

        {/* Executive summary --------------------------------------------- */}
        {report ? (
          <Card title="Executive summary" eyebrow="Production intelligence report">
            <p className="report-prose">{report.executive_summary}</p>

            {report.opportunities.length > 0 && (
              <div style={{ marginTop: 18 }}>
                <div className="eyebrow" style={{ marginBottom: 7 }}>
                  Opportunities
                </div>
                <ul className="list-clean">
                  {report.opportunities.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            <div style={{ marginTop: 18 }}>
              <div className="eyebrow" style={{ marginBottom: 7 }}>
                Critical risk summary
              </div>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.65 }}>
                {report.critical_risks_summary}
              </p>
            </div>
          </Card>
        ) : (
          <Empty
            title="No executive report was generated"
            hint="The underlying findings are still available in the evidence and risk views."
          />
        )}

        <div className="grid grid-2" style={{ alignItems: "start" }}>
          {/* Score breakdown --------------------------------------------- */}
          {assessment && (
            <Card title="How this score was calculated" eyebrow="Deterministic, computed in code">
              {assessment.components.map((component) => (
                <div className="breakdown-row" key={component.name}>
                  <div>
                    <div className="breakdown-name">{component.name}</div>
                    <div className="dim" style={{ fontSize: 11, lineHeight: 1.45 }}>
                      {component.detail}
                    </div>
                  </div>
                  <Bar
                    value={component.points}
                    max={component.max_points}
                    colour={
                      component.points / component.max_points > 0.66
                        ? "var(--verified)"
                        : component.points / component.max_points > 0.33
                          ? "var(--medium)"
                          : "var(--critical)"
                    }
                  />
                  <div className="breakdown-points">
                    {component.points}/{component.max_points}
                  </div>
                </div>
              ))}
              <p className="dim" style={{ fontSize: 11, marginTop: 12, lineHeight: 1.55 }}>
                {assessment.methodology_note}
              </p>
            </Card>
          )}

          {/* Recommended actions ------------------------------------------ */}
          <Card
            title="Recommended actions"
            eyebrow="What to do next"
            action={
              <span className="dim" style={{ fontSize: 12 }}>
                {project.recommendations.length} actions
              </span>
            }
          >
            {project.recommendations.length === 0 ? (
              <Empty title="No recommendations were produced" />
            ) : (
              project.recommendations.map((recommendation, index) => (
                <div className="action-item" key={recommendation.id}>
                  <div className="action-index">{index + 1}</div>
                  <div className="col" style={{ minWidth: 0, gap: 4 }}>
                    <span style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.5 }}>
                      {recommendation.action}
                    </span>
                    <span className="dim" style={{ fontSize: 12, lineHeight: 1.5 }}>
                      {recommendation.rationale}
                    </span>
                    <span className="dim mono">{recommendation.owner_hint}</span>
                  </div>
                  <SeverityBadge severity={recommendation.priority} />
                </div>
              ))
            )}
          </Card>
        </div>

        {/* Top risks ------------------------------------------------------ */}
        {topRisks.length > 0 && (
          <Card
            title="Most serious risks"
            eyebrow="Risk center"
            action={
              <Link className="btn btn-sm" to={`/projects/${id}/risks`}>
                View all {project.risks.length}
              </Link>
            }
          >
            <div className="grid grid-2">
              {topRisks.map((risk) => (
                <div
                  className={`risk-card ${risk.severity.toLowerCase()}`}
                  key={risk.id}
                  style={{ padding: 14 }}
                >
                  <div className="row-between" style={{ marginBottom: 7 }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{risk.title}</span>
                    <SeverityBadge severity={risk.severity} />
                  </div>
                  <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.55 }}>
                    {risk.reasoning}
                  </p>
                  {risk.requires_human_confirmation && (
                    <div style={{ marginTop: 9 }}>
                      <span className="badge badge-medium">Requires human confirmation</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Open questions and next steps ---------------------------------- */}
        {report && (
          <div className="grid grid-2" style={{ alignItems: "start" }}>
            <Card title="Questions requiring human confirmation" eyebrow="Do not assume these">
              {report.open_questions.length === 0 ? (
                <p className="dim" style={{ fontSize: 13 }}>
                  No outstanding questions were identified.
                </p>
              ) : (
                <ul className="list-clean">
                  {report.open_questions.map((question, index) => (
                    <li key={index}>{question}</li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Suggested next steps" eyebrow="In order">
              <ul className="list-clean">
                {report.next_steps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ul>
            </Card>
          </div>
        )}

        {/* Pipeline trace -------------------------------------------------- */}
        {project.runs.length > 0 && (
          <Card title="Agent execution trace" eyebrow="Observability">
            <div className="stack-sm">
              {project.runs.map((run) => (
                <div className="row-between" key={run.stage} style={{ fontSize: 12.5 }}>
                  <div className="row" style={{ gap: 9, minWidth: 0 }}>
                    <span
                      className="badge"
                      style={{
                        color: run.status === "OK" ? "var(--verified)" : "var(--critical)",
                        background: "transparent",
                        borderColor: "var(--border)",
                      }}
                    >
                      {run.status}
                    </span>
                    <span>{run.label}</span>
                    <span className="dim">{run.detail}</span>
                  </div>
                  <span className="dim mono">
                    {run.duration_ms !== null ? `${run.duration_ms} ms` : "—"}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}

        <p className="dim" style={{ fontSize: 11.5, lineHeight: 1.6, maxWidth: 760 }}>
          CineScout performs research, not legal advice. Regulatory, permit, insurance and
          safety findings are signals gathered from public sources and must be confirmed
          with the relevant authority or a qualified professional before you commit budget
          or crew. Every claim in this report links to the source it came from.
        </p>
      </div>
    </>
  );
}

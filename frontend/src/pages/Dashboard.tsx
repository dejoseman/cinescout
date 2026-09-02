import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import Topbar from "../components/Topbar";
import { Card, Empty, Metric } from "../components/ui";
import { api } from "../lib/api";
import type { ProjectSummary } from "../lib/types";

function statusTone(status: ProjectSummary["status"]): string {
  if (status === "COMPLETE") return "var(--verified)";
  if (status === "FAILED") return "var(--critical)";
  if (status === "RUNNING") return "var(--accent)";
  return "var(--text-3)";
}

function readinessTone(score: number | null): string {
  if (score === null) return "var(--text-3)";
  if (score >= 75) return "var(--verified)";
  if (score >= 50) return "var(--medium)";
  if (score >= 30) return "var(--high)";
  return "var(--critical)";
}

function ProjectRow({ project }: { project: ProjectSummary }) {
  const live = project.status === "RUNNING" || project.status === "QUEUED";
  const target = live ? `/projects/${project.id}/live` : `/projects/${project.id}`;

  return (
    <Link to={target} className="project-card">
      <div className="row-between" style={{ marginBottom: 10 }}>
        <div className="col" style={{ minWidth: 0 }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{project.title}</span>
          <span className="dim" style={{ fontSize: 12 }}>
            {[project.city, project.country].filter(Boolean).join(", ")}
          </span>
        </div>
        <span className="badge badge-neutral" style={{ color: statusTone(project.status) }}>
          <span className="pip" />
          {project.status}
        </span>
      </div>

      <div className="row wrap" style={{ gap: 18 }}>
        <div className="col">
          <span style={{ fontSize: 19, fontWeight: 700, color: readinessTone(project.readiness_score) }}>
            {project.readiness_score === null ? "—" : `${project.readiness_score}%`}
          </span>
          <span className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Readiness
          </span>
        </div>
        <div className="col">
          <span style={{ fontSize: 19, fontWeight: 700 }}>
            {project.critical_risks || "—"}
          </span>
          <span className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Critical risks
          </span>
        </div>
        <div className="col">
          <span style={{ fontSize: 19, fontWeight: 700 }}>{project.total_sources || "—"}</span>
          <span className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Sources
          </span>
        </div>
        <div className="col">
          <span style={{ fontSize: 19, fontWeight: 700 }}>{project.open_actions || "—"}</span>
          <span className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Actions
          </span>
        </div>
      </div>
    </Link>
  );
}

export default function Dashboard() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  const completed = projects.filter((p) => p.status === "COMPLETE");
  const averageReadiness = completed.length
    ? Math.round(
        completed.reduce((sum, p) => sum + (p.readiness_score ?? 0), 0) / completed.length,
      )
    : null;
  const totalCritical = projects.reduce((sum, p) => sum + p.critical_risks, 0);
  const totalActions = projects.reduce((sum, p) => sum + p.open_actions, 0);
  const totalSources = projects.reduce((sum, p) => sum + p.total_sources, 0);

  return (
    <>
      <Topbar
        title="Dashboard"
        subtitle={`${projects.length} production${projects.length === 1 ? "" : "s"}`}
        actions={
          <button className="btn btn-primary btn-sm" onClick={() => navigate("/new")}>
            New production
          </button>
        }
      />

      <div className="content">
        {projects.length === 0 && !loading && (
          <div className="hero">
            <h1>Can we realistically make this production?</h1>
            <p>
              Large studios have entire departments for production research. Independent
              creators usually do it themselves, across dozens of tabs, and often discover
              the blocker far too late. CineScout gives every creator an autonomous
              production research department — one that plans its own research, searches
              the live web, checks its own sources, and hands back a decision with the
              evidence attached.
            </p>
            <div className="row" style={{ marginTop: 18 }}>
              <button className="btn btn-primary" onClick={() => navigate("/new")}>
                Start a production brief
              </button>
            </div>
          </div>
        )}

        {projects.length > 0 && (
          <div className="grid grid-4" style={{ marginBottom: 20 }}>
            <Metric
              value={averageReadiness === null ? "—" : `${averageReadiness}%`}
              label="Avg. readiness"
              tone={readinessTone(averageReadiness)}
            />
            <Metric
              value={totalCritical}
              label="Critical risks"
              tone={totalCritical > 0 ? "var(--critical)" : undefined}
            />
            <Metric value={totalActions} label="Outstanding actions" />
            <Metric value={totalSources} label="Sources gathered" />
          </div>
        )}

        <Card
          title="Productions"
          action={
            <button className="btn btn-sm" onClick={() => navigate("/new")}>
              New
            </button>
          }
        >
          {loading ? (
            <div className="row dim" style={{ padding: 20 }}>
              <span className="spinner" />
              <span style={{ marginLeft: 8 }}>Loading productions…</span>
            </div>
          ) : projects.length === 0 ? (
            <Empty
              title="No productions yet"
              hint="Create a production brief and CineScout will research it against the live web."
            />
          ) : (
            <div className="grid grid-2">
              {projects.map((project) => (
                <ProjectRow key={project.id} project={project} />
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

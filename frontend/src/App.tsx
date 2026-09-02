import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useParams } from "react-router-dom";

import { api } from "./lib/api";
import type { HealthStatus } from "./lib/types";
import Dashboard from "./pages/Dashboard";
import EvidenceExplorer from "./pages/EvidenceExplorer";
import IntelligenceReport from "./pages/IntelligenceReport";
import LiveResearch from "./pages/LiveResearch";
import NewProduction from "./pages/NewProduction";
import RiskCenter from "./pages/RiskCenter";

/** Project-scoped navigation only appears once a project is open. */
function ProjectNav() {
  const { id } = useParams();
  if (!id) return null;

  return (
    <>
      <div className="nav-label" style={{ paddingTop: 18 }}>
        Current project
      </div>
      <nav className="nav">
        <NavLink to={`/projects/${id}`} end className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
          Intelligence report
        </NavLink>
        <NavLink to={`/projects/${id}/evidence`} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
          Evidence explorer
        </NavLink>
        <NavLink to={`/projects/${id}/risks`} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
          Risk center
        </NavLink>
        <NavLink to={`/projects/${id}/live`} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
          Live research
        </NavLink>
      </nav>
    </>
  );
}

function Sidebar({ health }: { health: HealthStatus | null }) {
  const ready = health?.parallel_configured && health?.gemini_configured;

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">CS</div>
        <div className="col">
          <span className="brand-name">CineScout</span>
          <span className="brand-tag">Production intelligence</span>
        </div>
      </div>

      <div>
        <div className="nav-label">Workspace</div>
        <nav className="nav">
          <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            Dashboard
          </NavLink>
          <NavLink to="/new" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            New production
          </NavLink>
        </nav>
      </div>

      <Routes>
        <Route path="/projects/:id/*" element={<ProjectNav />} />
        <Route path="*" element={null} />
      </Routes>

      <div className="sidebar-foot">
        <div className="row" style={{ gap: 6 }}>
          <span
            className="pip"
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: ready ? "var(--verified)" : "var(--high)",
              display: "inline-block",
            }}
          />
          <span>{ready ? "Integrations ready" : "Integrations incomplete"}</span>
        </div>
        {health && (
          <>
            <div className="mono dim">Gemini · {health.model}</div>
            <div className="mono dim">
              Parallel Search · {health.parallel_configured ? "connected" : "not configured"}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <div className="shell">
      <Sidebar health={health} />
      <div className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewProduction health={health} />} />
          <Route path="/projects/:id" element={<IntelligenceReport />} />
          <Route path="/projects/:id/live" element={<LiveResearch />} />
          <Route path="/projects/:id/evidence" element={<EvidenceExplorer />} />
          <Route path="/projects/:id/risks" element={<RiskCenter />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import Topbar from "../components/Topbar";
import { Callout, Card, Metric, TaskBadge } from "../components/ui";
import { streamProject } from "../lib/api";
import type { StageName, StreamEvent, TaskStatus } from "../lib/types";

/** The pipeline, in execution order. Mirrors `Stage` in the backend. */
const STAGES: Array<{ id: StageName; label: string; note: string }> = [
  { id: "brief", label: "Understanding production brief", note: "Gemini extracts requirements and plans the research" },
  { id: "research", label: "Searching external sources", note: "Parallel Search executes every planned task" },
  { id: "evidence", label: "Analysing evidence", note: "Excerpts become individually cited claims" },
  { id: "verification", label: "Cross-checking information", note: "Claims are corroborated or flagged as conflicting" },
  { id: "risk", label: "Assessing risks", note: "Findings become production risks and gaps" },
  { id: "scoring", label: "Computing readiness", note: "Deterministic scoring, no model involved" },
  { id: "recommendation", label: "Preparing recommendations", note: "Findings become prioritised actions" },
  { id: "report", label: "Preparing production report", note: "The executive summary a producer can act on" },
];

interface TaskState {
  id: string;
  category: string;
  question: string;
  priority: string;
  queries: string[];
  status: TaskStatus;
  sources: number;
  latency: number | null;
  error?: string;
}

export default function LiveResearch() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [stageStatus, setStageStatus] = useState<Record<string, "done" | "active" | "error">>({});
  const [stageDetail, setStageDetail] = useState<Record<string, string>>({});
  const [tasks, setTasks] = useState<TaskState[]>([]);
  const [planSummary, setPlanSummary] = useState("");
  const [missing, setMissing] = useState<string[]>([]);
  const [sources, setSources] = useState<StreamEvent[]>([]);
  const [claims, setClaims] = useState<StreamEvent[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [connectionLost, setConnectionLost] = useState(false);

  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;

    const unsubscribe = streamProject(
      id,
      (event) => {
        switch (event.type) {
          case "stage_started":
            if (event.stage) {
              setStageStatus((current) => {
                const next = { ...current };
                // Anything before the newly active stage has necessarily finished.
                for (const stage of STAGES) {
                  if (stage.id === event.stage) break;
                  if (next[stage.id] !== "error") next[stage.id] = "done";
                }
                next[event.stage!] = "active";
                return next;
              });
            }
            break;

          case "stage_completed":
            if (event.stage) {
              setStageStatus((current) => ({ ...current, [event.stage!]: "done" }));
              if (event.metrics) {
                setStageDetail((current) => ({
                  ...current,
                  [event.stage!]: Object.entries(event.metrics!)
                    .map(([key, value]) =>
                      typeof value === "object" && value !== null
                        ? Object.entries(value as Record<string, unknown>)
                            .map(([k, v]) => `${v} ${k.toLowerCase()}`)
                            .join(", ")
                        : `${value} ${key.replace(/_/g, " ")}`,
                    )
                    .join(" · "),
                }));
              }
            }
            break;

          case "research_plan_ready":
            setPlanSummary(event.summary ?? "");
            setMissing(event.missing_information ?? []);
            setTasks(
              (event.tasks ?? []).map((task) => ({
                id: task.id,
                category: task.category,
                question: task.question,
                priority: task.priority,
                queries: task.queries,
                status: "PENDING" as TaskStatus,
                sources: 0,
                latency: null,
              })),
            );
            break;

          case "search_progress":
            setTasks((current) =>
              current.map((task) =>
                task.id === event.task_id
                  ? {
                      ...task,
                      status: (event.status as TaskStatus) ?? task.status,
                      sources: event.sources ?? task.sources,
                      latency: event.latency_ms ?? task.latency,
                      error: event.error,
                    }
                  : task,
              ),
            );
            break;

          case "source_found":
            setSources((current) => [...current, event]);
            break;

          case "evidence_found":
            setClaims((current) => [...current, event]);
            break;

          case "error":
            if (event.stage) {
              setStageStatus((current) => ({ ...current, [event.stage!]: "error" }));
            }
            if (event.recoverable === false) setFailure(event.message ?? "The pipeline failed.");
            break;

          case "failed":
            setFailure(event.message ?? "The analysis failed.");
            break;

          case "complete":
            setDone(true);
            setStageStatus((current) => {
              const next = { ...current };
              STAGES.forEach((stage) => {
                if (next[stage.id] !== "error") next[stage.id] = "done";
              });
              return next;
            });
            // Give the completed state a beat to register before navigating.
            setTimeout(() => navigate(`/projects/${id}`), 1400);
            break;
        }
      },
      () => setConnectionLost(true),
    );

    return unsubscribe;
  }, [id, navigate]);

  // Keep the newest evidence visible without yanking the page around.
  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [claims.length]);

  const activeStage = useMemo(
    () => STAGES.find((stage) => stageStatus[stage.id] === "active"),
    [stageStatus],
  );

  const completedTasks = tasks.filter((t) => t.status !== "PENDING" && t.status !== "RUNNING");
  const failedTasks = tasks.filter((t) => t.status === "FAILED");
  const uniqueDomains = new Set(sources.map((s) => s.domain)).size;

  return (
    <>
      <Topbar
        title="Live research"
        subtitle={done ? "Analysis complete" : activeStage?.label ?? "Starting…"}
        actions={
          done ? (
            <button className="btn btn-primary btn-sm" onClick={() => navigate(`/projects/${id}`)}>
              View report
            </button>
          ) : (
            <span className="row dim" style={{ fontSize: 12 }}>
              <span className="pulse" />
              <span style={{ marginLeft: 6 }}>Agents working</span>
            </span>
          )
        }
      />

      <div className="content wide">
        {failure && (
          <div style={{ marginBottom: 16 }}>
            <Callout tone="error">
              <strong>The analysis could not complete.</strong>
              <div style={{ marginTop: 5 }}>{failure}</div>
              <div style={{ marginTop: 7 }}>
                CineScout does not fall back to unverified model output when live research
                fails — no report is better than an unfounded one.
              </div>
            </Callout>
          </div>
        )}

        {connectionLost && !done && !failure && (
          <div style={{ marginBottom: 16 }}>
            <Callout tone="warn">
              The live connection dropped. The analysis is still running on the server —
              reload this page to reconnect.
            </Callout>
          </div>
        )}

        <div className="grid grid-4" style={{ marginBottom: 18 }}>
          <Metric value={tasks.length || "—"} label="Research tasks" />
          <Metric
            value={sources.length || "—"}
            label="Sources retrieved"
            tone={sources.length ? "var(--accent)" : undefined}
          />
          <Metric value={uniqueDomains || "—"} label="Independent domains" />
          <Metric
            value={claims.length || "—"}
            label="Claims extracted"
            tone={claims.length ? "var(--verified)" : undefined}
          />
        </div>

        <div className="grid" style={{ gridTemplateColumns: "300px 1fr", alignItems: "start" }}>
          <Card title="Agent pipeline" eyebrow="Orchestration">
            <div className="rail">
              {STAGES.map((stage, index) => {
                const status = stageStatus[stage.id];
                return (
                  <div
                    key={stage.id}
                    className={`rail-step ${status === "done" ? "done" : status === "active" ? "active" : status === "error" ? "error" : ""}`}
                  >
                    <div className="rail-node">
                      {status === "done" ? "✓" : status === "error" ? "!" : index + 1}
                    </div>
                    <div className="rail-body">
                      <div className="row" style={{ gap: 7 }}>
                        <span className="rail-title">{stage.label}</span>
                        {status === "active" && <span className="pulse" />}
                      </div>
                      <div className="rail-detail">{stageDetail[stage.id] ?? stage.note}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          <div className="stack">
            {planSummary && (
              <Card title="Research plan" eyebrow="Stage 1 · Gemini">
                <p className="muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
                  {planSummary}
                </p>
                {missing.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div className="eyebrow" style={{ marginBottom: 6 }}>
                      Missing from the brief
                    </div>
                    <ul className="list-clean">
                      {missing.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>
            )}

            {tasks.length > 0 && (
              <Card
                title="Live web research"
                eyebrow="Stage 2 · Parallel Search API"
                action={
                  <span className="dim" style={{ fontSize: 12 }}>
                    {completedTasks.length} / {tasks.length} complete
                    {failedTasks.length > 0 && ` · ${failedTasks.length} failed`}
                  </span>
                }
              >
                <div className="stack-sm">
                  {tasks.map((task) => (
                    <div
                      key={task.id}
                      className={`task-card ${task.status === "RUNNING" ? "running" : task.status === "FAILED" ? "failed" : task.status === "OK" ? "ok" : ""}`}
                    >
                      <div className="row-between" style={{ marginBottom: 7 }}>
                        <div className="row" style={{ gap: 8, minWidth: 0 }}>
                          {task.status === "RUNNING" && <span className="spinner" />}
                          <span style={{ fontSize: 13, fontWeight: 500 }}>{task.question}</span>
                        </div>
                        <TaskBadge status={task.status} />
                      </div>

                      <div className="row wrap" style={{ gap: 5, marginBottom: 6 }}>
                        {task.queries.map((query, index) => (
                          <span className="query-pill" key={index}>
                            {query}
                          </span>
                        ))}
                      </div>

                      <div className="row dim" style={{ fontSize: 11.5, gap: 12 }}>
                        <span>{task.category.replace(/_/g, " ")}</span>
                        {task.status === "OK" && <span>{task.sources} sources</span>}
                        {task.latency !== null && <span>{task.latency} ms</span>}
                        {task.error && (
                          <span style={{ color: "var(--critical)" }}>{task.error}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {claims.length > 0 && (
              <Card
                title="Evidence as it is extracted"
                eyebrow="Stage 3 · every claim bound to a real source"
              >
                <div className="feed" ref={feedRef}>
                  {claims.map((claim, index) => (
                    <div className="feed-item" key={index}>
                      <span className="badge badge-accent mono">{claim.source_id}</span>
                      <span style={{ minWidth: 0 }}>{claim.claim}</span>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {sources.length > 0 && claims.length === 0 && (
              <Card title="Sources retrieved" eyebrow="Live from the open web">
                <div className="feed" ref={feedRef}>
                  {sources.map((source, index) => (
                    <div className="feed-item" key={index}>
                      <span className="badge badge-accent mono">{source.source_id}</span>
                      <div className="col" style={{ minWidth: 0 }}>
                        <span>{source.title || source.domain}</span>
                        <span className="dim mono">{source.domain}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {tasks.length === 0 && !failure && (
              <Card title="Planning" eyebrow="Stage 1">
                <div className="row dim" style={{ padding: 12 }}>
                  <span className="spinner" />
                  <span style={{ marginLeft: 9 }}>
                    Gemini is reading the brief and deciding what needs researching…
                  </span>
                </div>
              </Card>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

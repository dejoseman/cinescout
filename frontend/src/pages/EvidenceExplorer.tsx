import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import Topbar from "../components/Topbar";
import {
  Callout,
  Card,
  ConfidenceBadge,
  Empty,
  SourceLink,
  VerificationBadge,
} from "../components/ui";
import type { VerificationStatus } from "../lib/types";
import { sourceIndex, useProject, verificationIndex } from "../lib/useProject";

const FILTERS: Array<{ id: VerificationStatus | "ALL"; label: string }> = [
  { id: "ALL", label: "All" },
  { id: "VERIFIED", label: "Verified" },
  { id: "SUPPORTED", label: "Supported" },
  { id: "CONFLICTING", label: "Conflicting" },
  { id: "UNCONFIRMED", label: "Unconfirmed" },
  { id: "INSUFFICIENT_EVIDENCE", label: "Insufficient" },
];

export default function EvidenceExplorer() {
  const { id } = useParams();
  const { project, error, loading } = useProject(id);
  const [filter, setFilter] = useState<VerificationStatus | "ALL">("ALL");
  const [category, setCategory] = useState<string>("ALL");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const verifications = useMemo(() => verificationIndex(project), [project]);
  const sources = useMemo(() => sourceIndex(project), [project]);

  const categories = useMemo(
    () => Array.from(new Set(project?.evidence.map((e) => e.category) ?? [])).sort(),
    [project],
  );

  const visible = useMemo(() => {
    if (!project) return [];
    return project.evidence.filter((item) => {
      const status = verifications.get(item.id)?.status;
      const statusOk = filter === "ALL" || status === filter;
      const categoryOk = category === "ALL" || item.category === category;
      return statusOk && categoryOk;
    });
  }, [project, filter, category, verifications]);

  function toggle(evidenceId: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(evidenceId)) next.delete(evidenceId);
      else next.add(evidenceId);
      return next;
    });
  }

  if (loading) {
    return (
      <>
        <Topbar title="Evidence explorer" />
        <div className="content">
          <div className="row dim" style={{ padding: 30 }}>
            <span className="spinner" />
            <span style={{ marginLeft: 9 }}>Loading evidence…</span>
          </div>
        </div>
      </>
    );
  }

  if (error || !project) {
    return (
      <>
        <Topbar title="Evidence explorer" />
        <div className="content">
          <Callout tone="error">{error ?? "Project not found."}</Callout>
        </div>
      </>
    );
  }

  const counts = FILTERS.reduce<Record<string, number>>((acc, entry) => {
    acc[entry.id] =
      entry.id === "ALL"
        ? project.evidence.length
        : project.evidence.filter((item) => verifications.get(item.id)?.status === entry.id)
            .length;
    return acc;
  }, {});

  return (
    <>
      <Topbar
        title="Evidence explorer"
        subtitle={`${project.evidence.length} claims from ${project.sources.length} sources`}
      />

      <div className="content wide stack">
        <Callout tone="info">
          Every claim below was extracted from content retrieved live through the Parallel
          Search API and is bound to the exact source and excerpt it came from. Claims
          citing a source the retrieval layer never returned are discarded before they
          reach this view.
        </Callout>

        <Card>
          <div className="stack-sm">
            <div className="filter-bar">
              {FILTERS.map((entry) => (
                <button
                  key={entry.id}
                  className={`filter-chip ${filter === entry.id ? "active" : ""}`}
                  onClick={() => setFilter(entry.id)}
                >
                  {entry.label} ({counts[entry.id] ?? 0})
                </button>
              ))}
            </div>
            {categories.length > 1 && (
              <div className="filter-bar">
                <button
                  className={`filter-chip ${category === "ALL" ? "active" : ""}`}
                  onClick={() => setCategory("ALL")}
                >
                  All categories
                </button>
                {categories.map((entry) => (
                  <button
                    key={entry}
                    className={`filter-chip ${category === entry ? "active" : ""}`}
                    onClick={() => setCategory(entry)}
                  >
                    {entry.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            )}
          </div>
        </Card>

        {visible.length === 0 ? (
          <Empty
            title="No claims match this filter"
            hint={
              project.evidence.length === 0
                ? "No verifiable claims were extracted in this run."
                : "Try a different verification status or category."
            }
          />
        ) : (
          <div className="stack-sm">
            {visible.map((item) => {
              const verification = verifications.get(item.id);
              const source = sources.get(item.source_id);
              const isOpen = expanded.has(item.id);

              return (
                <article className="evidence-item" key={item.id}>
                  <div
                    className="evidence-head"
                    onClick={() => toggle(item.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggle(item.id);
                      }
                    }}
                  >
                    <div className="col" style={{ minWidth: 0, gap: 7, flex: 1 }}>
                      <p className="evidence-claim">{item.claim}</p>
                      <div className="row wrap" style={{ gap: 6 }}>
                        {verification && <VerificationBadge status={verification.status} />}
                        <ConfidenceBadge confidence={item.confidence} />
                        <span className="badge badge-neutral">
                          {item.category.replace(/_/g, " ")}
                        </span>
                        {verification?.staleness_flag && (
                          <span className="badge badge-medium">May be out of date</span>
                        )}
                        {source && (
                          <span className="dim mono">
                            {item.source_id} · {source.domain}
                          </span>
                        )}
                      </div>
                    </div>
                    <span className="dim" style={{ fontSize: 16, lineHeight: 1 }}>
                      {isOpen ? "−" : "+"}
                    </span>
                  </div>

                  {isOpen && (
                    <div className="evidence-body stack-sm">
                      <div>
                        <div className="eyebrow" style={{ marginBottom: 6 }}>
                          Verbatim excerpt from the source
                        </div>
                        <blockquote className="excerpt">{item.excerpt}</blockquote>
                      </div>

                      {source && (
                        <div>
                          <div className="eyebrow" style={{ marginBottom: 5 }}>
                            Source
                          </div>
                          <div className="col" style={{ gap: 3 }}>
                            <span style={{ fontSize: 13 }}>{source.title || source.domain}</span>
                            <SourceLink url={source.url}>{source.url}</SourceLink>
                            {source.publish_date && (
                              <span className="dim" style={{ fontSize: 11.5 }}>
                                Published {source.publish_date}
                              </span>
                            )}
                          </div>
                        </div>
                      )}

                      {verification && (
                        <div>
                          <div className="eyebrow" style={{ marginBottom: 5 }}>
                            Verification reasoning
                          </div>
                          <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                            {verification.reasoning}
                          </p>
                          {verification.corroborating_source_ids.length > 0 && (
                            <div className="row wrap" style={{ gap: 5, marginTop: 7 }}>
                              <span className="dim" style={{ fontSize: 11.5 }}>
                                Corroborated by:
                              </span>
                              {verification.corroborating_source_ids.map((sid) => (
                                <span className="badge badge-verified mono" key={sid}>
                                  {sid}
                                </span>
                              ))}
                            </div>
                          )}
                          {verification.contradicting_source_ids.length > 0 && (
                            <div className="row wrap" style={{ gap: 5, marginTop: 5 }}>
                              <span className="dim" style={{ fontSize: 11.5 }}>
                                Contradicted by:
                              </span>
                              {verification.contradicting_source_ids.map((sid) => (
                                <span className="badge badge-conflict mono" key={sid}>
                                  {sid}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        {/* Source catalogue -------------------------------------------------- */}
        <Card
          title="Source catalogue"
          eyebrow="Retrieved live via Parallel Search"
          action={
            <span className="dim" style={{ fontSize: 12 }}>
              {new Set(project.sources.map((s) => s.domain)).size} independent domains
            </span>
          }
        >
          {project.sources.length === 0 ? (
            <Empty title="No sources were retrieved" />
          ) : (
            <div className="stack-sm">
              {project.sources.map((source) => (
                <div className="row-between" key={source.id} style={{ gap: 12 }}>
                  <div className="row" style={{ gap: 9, minWidth: 0 }}>
                    <span className="badge badge-accent mono">{source.id}</span>
                    <div className="col" style={{ minWidth: 0 }}>
                      <span style={{ fontSize: 12.5 }}>{source.title || source.domain}</span>
                      <SourceLink url={source.url}>{source.url}</SourceLink>
                    </div>
                  </div>
                  <span className="dim mono">{source.publish_date ?? "undated"}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

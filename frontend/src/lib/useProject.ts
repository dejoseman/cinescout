import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import type { Project } from "./types";

/** Loads one project, exposing loading and error states rather than hiding them. */
export function useProject(id: string | undefined) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!id) return;
    try {
      setProject(await api.getProject(id));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this project.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    void reload();
  }, [reload]);

  return { project, error, loading, reload };
}

/** Maps evidence ids to their verification record for quick lookup. */
export function verificationIndex(project: Project | null) {
  const index = new Map<string, Project["verifications"][number]>();
  project?.verifications.forEach((v) => index.set(v.evidence_id, v));
  return index;
}

/** Maps source ids to sources for citation rendering. */
export function sourceIndex(project: Project | null) {
  const index = new Map<string, Project["sources"][number]>();
  project?.sources.forEach((s) => index.set(s.id, s));
  return index;
}

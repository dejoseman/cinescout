/** Thin API client. Every network failure is surfaced, never swallowed. */

import type {
  HealthStatus,
  ProductionBrief,
  Project,
  ProjectSummary,
  StreamEvent,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Could not reach the CineScout service.", 0);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        // FastAPI validation errors arrive as a list of field errors.
        detail = body.detail
          .map((e: { loc?: string[]; msg?: string }) =>
            `${e.loc?.slice(1).join(".") ?? "field"}: ${e.msg ?? "invalid"}`,
          )
          .join("; ");
      }
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthStatus>("/api/health"),

  demoBrief: () => request<ProductionBrief>("/api/demo-brief"),

  listProjects: () =>
    request<{ projects: ProjectSummary[] }>("/api/projects").then((r) => r.projects),

  getProject: (id: string) => request<Project>(`/api/projects/${id}`),

  createProject: (brief: Partial<ProductionBrief>) =>
    request<{ id: string; status: string }>("/api/projects", {
      method: "POST",
      body: JSON.stringify(brief),
    }),
};

/**
 * Subscribe to a project's live pipeline events.
 *
 * Returns an unsubscribe function. The browser's EventSource reconnects on its
 * own; the server replays history on reconnect, so no events are lost.
 */
export function streamProject(
  projectId: string,
  onEvent: (event: StreamEvent) => void,
  onError?: () => void,
): () => void {
  const source = new EventSource(`/api/projects/${projectId}/stream`);

  source.onmessage = (message) => {
    try {
      const parsed = JSON.parse(message.data) as StreamEvent;
      if (parsed.type !== "heartbeat") {
        onEvent(parsed);
      }
      if (parsed.type === "complete" || parsed.type === "failed") {
        source.close();
      }
    } catch {
      /* a malformed frame must not kill the stream */
    }
  };

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      onError?.();
    }
  };

  return () => source.close();
}

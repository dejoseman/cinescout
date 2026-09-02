import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import Topbar from "../components/Topbar";
import { Callout, Card } from "../components/ui";
import { api } from "../lib/api";
import type { HealthStatus, ProductionBrief } from "../lib/types";

const EMPTY: Partial<ProductionBrief> = {
  title: "",
  project_type: "Independent feature film",
  genre: "",
  country: "",
  city: "",
  budget_amount: null,
  budget_currency: "USD",
  shooting_days: null,
  shooting_period: "",
  locations: [],
  requirements: [],
  target_audience: "",
  constraints: "",
  free_text: "",
};

const PROJECT_TYPES = [
  "Independent feature film",
  "Short film",
  "Documentary",
  "Television series",
  "Commercial",
  "Music video",
  "Web series",
  "Social / creator content",
];

/** A list input that reads as chips - closer to how a producer thinks in items. */
function ListField({
  label,
  hint,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  hint?: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    const value = draft.trim();
    if (!value) return;
    onChange([...values, value]);
    setDraft("");
  }

  return (
    <div className="field">
      <label>{label}</label>
      {values.length > 0 && (
        <div className="chip-input" style={{ marginBottom: 4 }}>
          {values.map((value, index) => (
            <span className="chip" key={`${value}-${index}`}>
              {value}
              <button
                type="button"
                aria-label={`Remove ${value}`}
                onClick={() => onChange(values.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        className="input"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        onBlur={commit}
      />
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

export default function NewProduction({ health }: { health: HealthStatus | null }) {
  const [brief, setBrief] = useState<Partial<ProductionBrief>>(EMPTY);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const notConfigured = health !== null && (!health.parallel_configured || !health.gemini_configured);

  function set<K extends keyof ProductionBrief>(key: K, value: ProductionBrief[K]) {
    setBrief((current) => ({ ...current, [key]: value }));
  }

  async function loadDemo() {
    try {
      setBrief(await api.demoBrief());
      setError(null);
    } catch {
      setError("Could not load the demo brief.");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { id } = await api.createProject(brief);
      navigate(`/projects/${id}/live`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the analysis.");
      setSubmitting(false);
    }
  }

  return (
    <>
      <Topbar
        title="New production"
        subtitle="Tell CineScout what you are making"
        actions={
          <button type="button" className="btn btn-sm" onClick={loadDemo}>
            Load demo brief
          </button>
        }
      />

      <div className="content">
        <div className="hero" style={{ paddingTop: 8 }}>
          <h1>What are you producing?</h1>
          <p>
            The more specific the brief, the sharper the research. CineScout will identify
            what it does not know and tell you, rather than guessing.
          </p>
        </div>

        {notConfigured && (
          <div style={{ marginBottom: 16 }}>
            <Callout tone="warn">
              <strong>Live research is not configured.</strong> CineScout needs a Parallel
              Search API key and Gemini credentials before it can run. It will refuse to
              produce a report without them, because a report without live retrieval would
              not be evidence-backed. See the README for setup.
            </Callout>
          </div>
        )}

        {error && (
          <div style={{ marginBottom: 16 }}>
            <Callout tone="error">{error}</Callout>
          </div>
        )}

        <form onSubmit={submit} className="stack">
          <Card title="Production brief" eyebrow="Step 1">
            <div className="stack">
              <div className="grid grid-2">
                <div className="field">
                  <label htmlFor="title">Project title *</label>
                  <input
                    id="title"
                    className="input"
                    required
                    minLength={2}
                    maxLength={120}
                    value={brief.title ?? ""}
                    onChange={(e) => set("title", e.target.value)}
                    placeholder="Shadow District"
                  />
                </div>
                <div className="field">
                  <label htmlFor="type">Project type</label>
                  <select
                    id="type"
                    className="select"
                    value={brief.project_type ?? ""}
                    onChange={(e) => set("project_type", e.target.value)}
                  >
                    {PROJECT_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-3">
                <div className="field">
                  <label htmlFor="genre">Genre</label>
                  <input
                    id="genre"
                    className="input"
                    value={brief.genre ?? ""}
                    onChange={(e) => set("genre", e.target.value)}
                    placeholder="Crime thriller"
                  />
                </div>
                <div className="field">
                  <label htmlFor="country">Country *</label>
                  <input
                    id="country"
                    className="input"
                    required
                    minLength={2}
                    value={brief.country ?? ""}
                    onChange={(e) => set("country", e.target.value)}
                    placeholder="Nigeria"
                  />
                </div>
                <div className="field">
                  <label htmlFor="city">City or region</label>
                  <input
                    id="city"
                    className="input"
                    value={brief.city ?? ""}
                    onChange={(e) => set("city", e.target.value)}
                    placeholder="Lagos"
                  />
                </div>
              </div>

              <div className="grid grid-4">
                <div className="field">
                  <label htmlFor="budget">Approx. budget</label>
                  <input
                    id="budget"
                    className="input"
                    type="number"
                    min={0}
                    value={brief.budget_amount ?? ""}
                    onChange={(e) =>
                      set("budget_amount", e.target.value ? Number(e.target.value) : null)
                    }
                    placeholder="85000"
                  />
                </div>
                <div className="field">
                  <label htmlFor="currency">Currency</label>
                  <input
                    id="currency"
                    className="input"
                    maxLength={8}
                    value={brief.budget_currency ?? ""}
                    onChange={(e) => set("budget_currency", e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="days">Shooting days</label>
                  <input
                    id="days"
                    className="input"
                    type="number"
                    min={1}
                    value={brief.shooting_days ?? ""}
                    onChange={(e) =>
                      set("shooting_days", e.target.value ? Number(e.target.value) : null)
                    }
                    placeholder="12"
                  />
                </div>
                <div className="field">
                  <label htmlFor="period">Shooting period</label>
                  <input
                    id="period"
                    className="input"
                    value={brief.shooting_period ?? ""}
                    onChange={(e) => set("shooting_period", e.target.value)}
                    placeholder="February 2027"
                  />
                </div>
              </div>
            </div>
          </Card>

          <Card title="Locations and requirements" eyebrow="Step 2">
            <div className="grid grid-2">
              <ListField
                label="Required locations"
                placeholder="Rooftop overlooking the city — press Enter"
                hint="Press Enter to add each location."
                values={brief.locations ?? []}
                onChange={(next) => set("locations", next)}
              />
              <ListField
                label="Production requirements"
                placeholder="Night filming — press Enter"
                hint="Drone work, night shoots, crew size, stunts, animals, minors."
                values={brief.requirements ?? []}
                onChange={(next) => set("requirements", next)}
              />
            </div>
          </Card>

          <Card title="Context" eyebrow="Step 3">
            <div className="stack">
              <div className="grid grid-2">
                <div className="field">
                  <label htmlFor="audience">Target audience</label>
                  <input
                    id="audience"
                    className="input"
                    maxLength={200}
                    value={brief.target_audience ?? ""}
                    onChange={(e) => set("target_audience", e.target.value)}
                    placeholder="18-34 domestic plus festival circuit"
                  />
                </div>
                <div className="field">
                  <label htmlFor="constraints">Additional constraints</label>
                  <input
                    id="constraints"
                    className="input"
                    maxLength={1000}
                    value={brief.constraints ?? ""}
                    onChange={(e) => set("constraints", e.target.value)}
                    placeholder="No studio build, limited contingency"
                  />
                </div>
              </div>

              <div className="field">
                <label htmlFor="free">Tell CineScout about your production</label>
                <textarea
                  id="free"
                  className="textarea"
                  maxLength={4000}
                  value={brief.free_text ?? ""}
                  onChange={(e) => set("free_text", e.target.value)}
                  placeholder="What are you unsure about? What would stop this production? Write it the way you would explain it to a colleague."
                />
                <span className="hint">
                  {(brief.free_text ?? "").length} / 4000 characters
                </span>
              </div>
            </div>
          </Card>

          <div className="row-between">
            <span className="dim" style={{ fontSize: 12 }}>
              A full analysis runs eight agent stages and typically takes under two minutes.
            </span>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || !brief.title || !brief.country}
            >
              {submitting ? (
                <>
                  <span className="spinner" /> Starting analysis…
                </>
              ) : (
                "Run production analysis"
              )}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

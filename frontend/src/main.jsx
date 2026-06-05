import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE = "http://127.0.0.1:8000";
const EMPTY_AGENT_FORM = {
  project_purpose: "",
  project_rules: "",
  build_commands: "",
  test_commands: "",
  security_notes: "",
};

function App() {
  const [projectRoot, setProjectRoot] = useState("");
  const [projectRootMessage, setProjectRootMessage] = useState("");
  const [projects, setProjects] = useState([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [createForm, setCreateForm] = useState({ project_name: "", description: "", project_type: "" });
  const [agentForm, setAgentForm] = useState(EMPTY_AGENT_FORM);
  const [agentPreview, setAgentPreview] = useState("");
  const [agentsExists, setAgentsExists] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [scanHistory, setScanHistory] = useState([]);
  const [notes, setNotes] = useState([]);
  const [noteBody, setNoteBody] = useState("");
  const [changelog, setChangelog] = useState([]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.path === selectedPath) || null,
    [projects, selectedPath],
  );

  useEffect(() => {
    refreshProjects();
    loadChangelog();
  }, []);

  useEffect(() => {
    if (selectedPath) {
      loadNotes(selectedPath);
      loadScanHistory(selectedPath);
      checkAgentsExists(selectedPath);
      setAgentPreview("");
      setScanResult(null);
    }
  }, [selectedPath]);

  async function refreshProjects() {
    setLoading(true);
    try {
      const data = await api("/api/projects");
      setProjectRoot(data.project_root);
      setProjectRootMessage(data.message || "");
      setProjects(data.projects);
      const stillSelected = data.projects.some((project) => project.path === selectedPath);
      if ((!selectedPath || !stillSelected) && data.projects.length > 0) {
        setSelectedPath(data.projects[0].path);
      }
      if (!stillSelected && data.projects.length === 0) {
        setSelectedPath("");
        setScanResult(null);
        setScanHistory([]);
        setNotes([]);
        setAgentsExists(false);
        setAgentPreview("");
      }
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function createProject(event) {
    event.preventDefault();
    try {
      const created = await api("/api/projects", { method: "POST", body: createForm });
      setMessage(`Created ${created.name}`);
      setCreateForm({ project_name: "", description: "", project_type: "" });
      await refreshProjects();
      setSelectedPath(created.path);
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function loadChangelog() {
    try {
      const data = await api("/api/changelog");
      setChangelog(data.entries || []);
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function previewAgents(event) {
    event.preventDefault();
    if (!selectedPath) return;
    try {
      const data = await api("/api/agents/preview", {
        method: "POST",
        body: { project_path: selectedPath, ...agentForm },
      });
      setAgentPreview(data.content);
      setMessage("AGENTS.md preview generated.");
    } catch (error) {
      setMessage(error.message);
    }
  }

  function updateAgentField(field, value) {
    setAgentForm({ ...agentForm, [field]: value });
    setAgentPreview("");
  }

  async function writeAgents() {
    if (!selectedPath) return;
    try {
      const overwrite = agentsExists
        ? window.confirm("AGENTS.md already exists for this project. Overwrite it with the previewed content?")
        : false;

      if (agentsExists && !overwrite) {
        setMessage("Write canceled. Existing AGENTS.md was not changed.");
        return;
      }

      const data = await api("/api/agents/write", {
        method: "POST",
        body: { project_path: selectedPath, ...agentForm, overwrite },
      });
      if (data.confirmation_required) {
        setAgentsExists(true);
        setMessage(data.message);
        return;
      }
      setAgentPreview(data.content);
      setAgentsExists(true);
      setMessage(data.message || `Wrote ${data.path}`);
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function checkAgentsExists(path) {
    try {
      const data = await api(`/api/agents/exists?project_path=${encodeURIComponent(path)}`);
      setAgentsExists(Boolean(data.exists));
    } catch (error) {
      setAgentsExists(false);
      setMessage(error.message);
    }
  }

  async function runScan() {
    if (!selectedPath) return;
    try {
      const data = await api("/api/scans", { method: "POST", body: { project_path: selectedPath } });
      setScanResult(data);
      setMessage("Scan complete. Review the findings below.");
      await loadScanHistory(selectedPath);
      await refreshProjects();
      setSelectedPath(selectedPath);
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function loadScanHistory(path) {
    try {
      const data = await api(`/api/scans/history?project_path=${encodeURIComponent(path)}`);
      setScanHistory(data.scans);
    } catch (error) {
      setScanHistory([]);
      setMessage(error.message);
    }
  }

  async function loadNotes(path) {
    try {
      const data = await api(`/api/notes?project_path=${encodeURIComponent(path)}`);
      setNotes(data.notes);
    } catch (error) {
      setNotes([]);
      setMessage(error.message);
    }
  }

  async function addNote(event) {
    event.preventDefault();
    if (!selectedPath || !noteBody.trim()) return;
    try {
      await api("/api/notes", { method: "POST", body: { project_path: selectedPath, body: noteBody } });
      setNoteBody("");
      await loadNotes(selectedPath);
      await refreshProjects();
      setSelectedPath(selectedPath);
    } catch (error) {
      setMessage(error.message);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>CodexForge</h1>
          <p>Local project dashboard for reviewing AI-generated coding work before you run anything.</p>
        </div>
        <div className="root-pill" title={projectRoot}>{projectRoot || "Loading workspace root..."}</div>
      </header>

      {message && <div className="notice">{message}</div>}

      {projectRootMessage && <div className="notice">{projectRootMessage}</div>}

      <section className="layout">
        <aside className="sidebar">
          <div className="panel compact">
            <h2>Create Project</h2>
            <form onSubmit={createProject} className="stack">
              <input value={createForm.project_name} onChange={(event) => setCreateForm({ ...createForm, project_name: event.target.value })} placeholder="Project name" required />
              <input value={createForm.project_type} onChange={(event) => setCreateForm({ ...createForm, project_type: event.target.value })} placeholder="Project type" />
              <textarea value={createForm.description} onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })} placeholder="Description" rows="3" />
              <button type="submit">Create</button>
            </form>
          </div>

          <div className="panel compact">
            <h2>Projects</h2>
            {loading ? <p className="muted">Loading...</p> : null}
            <div className="project-list">
              {projects.map((project) => (
                <button
                  key={project.path}
                  className={`project-item ${project.path === selectedPath ? "selected" : ""}`}
                  onClick={() => setSelectedPath(project.path)}
                >
                  <span className="project-name">{project.name}</span>
                  <span className={`risk risk-${project.last_risk_level}`}>{project.last_risk_level}</span>
                  <span className="project-path">{project.path}</span>
                  <span className="project-meta">{project.notes_count} notes</span>
                  <span className="project-meta scan-time">Scan: {formatDate(project.last_scan_time)}</span>
                </button>
              ))}
              {!loading && projects.length === 0 ? <p className="muted">No project folders found.</p> : null}
            </div>
          </div>

          <Changelog entries={changelog} />
        </aside>

        <section className="content">
          {selectedProject ? (
            <>
              <ProjectHeader project={selectedProject} onScan={runScan} />
              <ScanReport result={scanResult || scanHistory[0]} />
              <AgentGenerator form={agentForm} updateField={updateAgentField} preview={agentPreview} exists={agentsExists} onPreview={previewAgents} onWrite={writeAgents} />
              <Notes notes={notes} noteBody={noteBody} setNoteBody={setNoteBody} onAdd={addNote} />
              <History scans={scanHistory} />
            </>
          ) : (
            <div className="panel empty-state">
              <h2>No Project Selected</h2>
              <p>Create a project or add folders under the configured workspace root.</p>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

function Changelog({ entries }) {
  return (
    <section className="panel compact">
      <h2>Changelog</h2>
      <div className="changelog-list">
        {entries.map((entry) => (
          <article className="changelog-entry" key={entry.version}>
            <div className="changelog-heading">
              <span className="version">{entry.version}</span>
              <strong>{entry.title}</strong>
            </div>
            <ul>
              {entry.changes.map((change) => (
                <li key={change}>{change}</li>
              ))}
            </ul>
          </article>
        ))}
        {entries.length === 0 ? <p className="muted">No changelog entries loaded.</p> : null}
      </div>
    </section>
  );
}

function ProjectHeader({ project, onScan }) {
  return (
    <section className="project-header">
      <div>
        <h2>{project.name}</h2>
        <p>{project.description || "No description yet."}</p>
        <div className="path-line">{project.path}</div>
      </div>
      <button onClick={onScan}>Scan</button>
    </section>
  );
}

function ScanReport({ result }) {
  const groups = useMemo(() => groupFindings(result?.findings || []), [result]);

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>Scan Report</h2>
          <p className="muted">Findings are review prompts, not proof of a problem.</p>
        </div>
        <span className={`risk large risk-${result?.overall_risk || "none"}`}>{result?.overall_risk || "none"}</span>
      </div>
      {!result ? <p className="muted">Run a scan to see findings for this project.</p> : null}
      {result && result.findings.length === 0 ? <p className="good">No scanner findings. Still review generated code before running it.</p> : null}
      {["high", "medium", "low"].map((severity) => (
        groups[severity].length > 0 && (
          <div className="finding-group" key={severity}>
            <h3>{severity} severity</h3>
            {groups[severity].map((finding, index) => (
              <article className="finding" key={`${finding.path}-${finding.type}-${index}`}>
                <div>
                  <strong>{finding.type}</strong>
                  <code>{finding.path}</code>
                </div>
                <p>{finding.explanation}</p>
              </article>
            ))}
          </div>
        )
      ))}
      {result ? <p className="review-note">Review high severity items first, then lifecycle scripts and files that launch processes or fetch remote content.</p> : null}
    </section>
  );
}

function AgentGenerator({ form, updateField, preview, exists, onPreview, onWrite }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>AGENTS.md Generator</h2>
          <p className="muted">{exists ? "AGENTS.md exists. Writing requires confirmation." : "Preview before writing anything to disk."}</p>
        </div>
      </div>
      <form onSubmit={onPreview} className="grid-form">
        <textarea value={form.project_purpose} onChange={(event) => updateField("project_purpose", event.target.value)} placeholder="Project purpose" rows="4" />
        <textarea value={form.project_rules} onChange={(event) => updateField("project_rules", event.target.value)} placeholder="Project rules" rows="4" />
        <textarea value={form.build_commands} onChange={(event) => updateField("build_commands", event.target.value)} placeholder="Build commands" rows="4" />
        <textarea value={form.test_commands} onChange={(event) => updateField("test_commands", event.target.value)} placeholder="Test commands" rows="4" />
        <textarea value={form.security_notes} onChange={(event) => updateField("security_notes", event.target.value)} placeholder="Security notes" rows="4" />
        <div className="actions">
          <button type="submit">Preview</button>
          <button type="button" onClick={onWrite} disabled={!preview}>Write AGENTS.md</button>
        </div>
      </form>
      {preview ? <pre className="preview">{preview}</pre> : null}
    </section>
  );
}

function Notes({ notes, noteBody, setNoteBody, onAdd }) {
  return (
    <section className="panel">
      <h2>Project Notes</h2>
      <form onSubmit={onAdd} className="note-form">
        <textarea value={noteBody} onChange={(event) => setNoteBody(event.target.value)} placeholder="Add a note" rows="3" />
        <button type="submit">Add Note</button>
      </form>
      <div className="notes-list">
        {notes.map((note) => (
          <article className="note" key={note.id}>
            <p>{note.body}</p>
            <time>{formatDate(note.created_at)}</time>
          </article>
        ))}
        {notes.length === 0 ? <p className="muted">No notes yet.</p> : null}
      </div>
    </section>
  );
}

function History({ scans }) {
  return (
    <section className="panel">
      <h2>Scan History</h2>
      <div className="history-list">
        {scans.map((scan) => (
          <div className="history-row" key={scan.id}>
            <span>{formatDate(scan.scan_date)}</span>
            <span className={`risk risk-${scan.overall_risk}`}>{scan.overall_risk}</span>
            <span>{scan.findings.length} findings</span>
          </div>
        ))}
        {scans.length === 0 ? <p className="muted">No scans saved yet.</p> : null}
      </div>
    </section>
  );
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "Request failed.");
  }
  return data;
}

function groupFindings(findings) {
  return findings.reduce(
    (groups, finding) => {
      const severity = groups[finding.severity] ? finding.severity : "low";
      groups[severity].push({ ...finding, severity });
      return groups;
    },
    { high: [], medium: [], low: [] },
  );
}

function formatDate(value) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

createRoot(document.getElementById("root")).render(<App />);

import { useEffect, useState } from 'react';
import { api, type ReviewerResponse, type RepoSummary, ApiError } from '../lib/api';

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'text-red-400 border-red-900/60 bg-red-950/30',
  important: 'text-amber-400 border-amber-900/60 bg-amber-950/30',
  advisory: 'text-slate-300 border-slate-800 bg-slate-900/40',
};

export default function ReviewerPage() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [repo, setRepo] = useState('');
  const [paths, setPaths] = useState('');
  const [result, setResult] = useState<ReviewerResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.repos().then((r) => {
      setRepos(r);
      if (r.length && !repo) setRepo(r[0].name);
    });
  }, [repo]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const files = paths
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await api.reviewer({ repo, changed_files: files });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">PR Reviewer</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Deterministic graph-based checks: circular imports, high fan-in changes,
          low-confidence callers, missing tests. No LLM call — runs against the live graph.
        </p>
      </header>

      <form onSubmit={submit} className="rounded-lg border border-slate-800 bg-slate-900/40 p-5 space-y-4">
        <label className="block text-sm">
          <span className="text-slate-400">Repo</span>
          <select
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm"
          >
            {repos.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          <span className="text-slate-400">Changed files (one per line or comma-separated)</span>
          <textarea
            value={paths}
            onChange={(e) => setPaths(e.target.value)}
            placeholder="apps/api/src/architect/ingest/writer.py&#10;apps/api/src/architect/ingest/resolver.py"
            rows={5}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-mono"
          />
        </label>

        <button
          type="submit"
          disabled={busy || !repo || !paths.trim()}
          className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-1.5 text-sm font-medium"
        >
          {busy ? 'Reviewing…' : 'Run review'}
        </button>
      </form>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {result && (
        <section className="space-y-4">
          <div className="flex items-baseline gap-4 text-sm">
            <span className="text-slate-400">Summary:</span>
            <span className="text-red-400">{result.summary.critical} critical</span>
            <span className="text-amber-400">{result.summary.important} important</span>
            <span className="text-slate-400">{result.summary.advisory} advisory</span>
          </div>
          {result.findings.length === 0 ? (
            <p className="text-slate-400 text-sm">No findings — go ahead.</p>
          ) : (
            <ul className="space-y-3">
              {result.findings.map((f, i) => (
                <li
                  key={i}
                  className={`rounded-lg border p-4 ${SEVERITY_COLOR[f.severity] ?? ''}`}
                >
                  <div className="flex items-center gap-3 text-xs uppercase tracking-wider">
                    <span className="font-semibold">{f.severity}</span>
                    <span className="text-slate-500">{f.rule}</span>
                  </div>
                  <p className="mt-2 text-sm">{f.message}</p>
                  {(f.file_path || f.qname) && (
                    <p className="mt-2 text-xs font-mono text-slate-500">
                      {f.file_path}
                      {f.line ? `:${f.line}` : ''}
                      {f.qname ? ` — ${f.qname}` : ''}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

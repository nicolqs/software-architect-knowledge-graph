import { useEffect, useState } from 'react';
import { api, type RefactorResponse, type RepoSummary, ApiError } from '../lib/api';

const RISK_COLOR: Record<string, string> = {
  high: 'text-red-400',
  medium: 'text-amber-400',
  low: 'text-slate-400',
};

export default function RefactorPage() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [repo, setRepo] = useState('');
  const [result, setResult] = useState<RefactorResponse | null>(null);
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
      setResult(await api.refactor({ repo }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Refactor Planner</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Graph analytics over the ingested repo: dead code, high-coupling modules.
          No LLM call. Output is ordered by architectural pain → easy wins.
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

        <button
          type="submit"
          disabled={busy || !repo}
          className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-1.5 text-sm font-medium"
        >
          {busy ? 'Analyzing…' : 'Run analysis'}
        </button>
      </form>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {result && (
        <section className="space-y-3">
          <div className="text-sm text-slate-400">
            {result.items.length} items — {' '}
            {Object.entries(result.summary)
              .map(([k, v]) => `${v} ${k}`)
              .join(', ')}
          </div>
          {result.items.length === 0 ? (
            <p className="text-slate-400 text-sm">Nothing to refactor — clean repo.</p>
          ) : (
            <ul className="space-y-2">
              {result.items.map((it) => (
                <li
                  key={`${it.kind}-${it.qname}`}
                  className="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
                >
                  <div className="flex items-center gap-3 text-xs uppercase tracking-wider">
                    <span className="text-slate-400">{it.kind.replace('_', ' ')}</span>
                    <span className={RISK_COLOR[it.risk]}>{it.risk} risk</span>
                    {it.blast_radius > 0 && (
                      <span className="text-slate-500">blast: {it.blast_radius}</span>
                    )}
                  </div>
                  <p className="mt-1 font-medium">{it.title}</p>
                  <p className="mt-1 text-sm text-slate-300">{it.rationale}</p>
                  {(it.file_path || it.qname) && (
                    <p className="mt-2 text-xs font-mono text-slate-500">
                      {it.file_path}
                      {it.line ? `:${it.line}` : ''}
                      {it.qname ? ` — ${it.qname}` : ''}
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

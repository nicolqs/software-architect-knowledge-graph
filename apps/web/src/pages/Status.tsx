import { useEffect, useState } from 'react';
import { api, type Health, type RepoSummary, ApiError } from '../lib/api';

export default function StatusPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [repos, setRepos] = useState<RepoSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : String(e)),
      );
    api
      .repos()
      .then(setRepos)
      .catch(() => setRepos([])); // tolerated; repos route may 500 on cold start
  }, []);

  return (
    <div className="space-y-6 max-w-3xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Status</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Backend health + ingested repos.
        </p>
      </header>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-3">Backend</h2>
        {error && <p className="text-red-400 text-sm">Unreachable: {error}</p>}
        {!error && !health && <p className="text-slate-400 text-sm">Checking…</p>}
        {health && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt className="text-slate-400">Status</dt>
            <dd className={health.status === 'ok' ? 'text-emerald-400' : 'text-amber-400'}>
              {health.status}
            </dd>
            <dt className="text-slate-400">API version</dt>
            <dd>{health.version}</dd>
            <dt className="text-slate-400">Neo4j</dt>
            <dd className={health.neo4j ? 'text-emerald-400' : 'text-red-400'}>
              {health.neo4j ? 'up' : 'down'}
            </dd>
            <dt className="text-slate-400">Postgres</dt>
            <dd className={health.postgres ? 'text-emerald-400' : 'text-red-400'}>
              {health.postgres ? 'up' : 'down'}
            </dd>
          </dl>
        )}
      </section>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-3">Ingested repos</h2>
        {repos === null && <p className="text-slate-400 text-sm">Loading…</p>}
        {repos !== null && repos.length === 0 && (
          <p className="text-slate-400 text-sm">
            No repos ingested yet. Run{' '}
            <code className="rounded bg-slate-800 px-1.5 py-0.5">
              make ingest REPO=…
            </code>
            .
          </p>
        )}
        {repos && repos.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-slate-400">
              <tr>
                <th className="py-1">Name</th>
                <th className="py-1 text-right">Files</th>
                <th className="py-1 text-right">Functions</th>
                <th className="py-1 text-right">Classes</th>
                <th className="py-1 text-right">Modules</th>
              </tr>
            </thead>
            <tbody>
              {repos.map((r) => (
                <tr key={r.name} className="border-t border-slate-800/60">
                  <td className="py-1.5 font-mono text-slate-200">{r.name}</td>
                  <td className="py-1.5 text-right">{r.files}</td>
                  <td className="py-1.5 text-right">{r.functions}</td>
                  <td className="py-1.5 text-right">{r.classes}</td>
                  <td className="py-1.5 text-right">{r.modules}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

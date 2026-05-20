import { useEffect, useState } from 'react';

type Health = {
  status: 'ok' | 'degraded';
  version: string;
  neo4j: boolean;
  postgres: boolean;
};

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json() as Promise<Health>)
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-xl w-full space-y-6">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">
            AI Autonomous Software Architect
          </h1>
          <p className="text-slate-400 mt-2">
            Knowledge-graph-backed agents that design, decompose, review, and refactor code.
          </p>
        </header>

        <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
          <h2 className="text-sm uppercase tracking-wider text-slate-400 mb-3">
            Backend status
          </h2>
          {error && <p className="text-red-400 text-sm">Unreachable: {error}</p>}
          {!error && !health && <p className="text-slate-400 text-sm">Checking…</p>}
          {health && (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <dt className="text-slate-400">Status</dt>
              <dd className={health.status === 'ok' ? 'text-emerald-400' : 'text-amber-400'}>
                {health.status}
              </dd>
              <dt className="text-slate-400">Version</dt>
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

        <footer className="text-xs text-slate-500">M0 bootstrap. Agents land in M3.</footer>
      </div>
    </main>
  );
}

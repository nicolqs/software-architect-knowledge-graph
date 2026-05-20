import { useState } from 'react';
import { api, ApiError, type Ticket } from '../lib/api';

export default function TicketsPage() {
  const [feature, setFeature] = useState('');
  const [repo, setRepo] = useState('');
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!feature.trim()) return;
    setBusy(true);
    setError(null);
    setTickets(null);
    try {
      const res = await api.tickets({
        feature,
        repo: repo.trim() || undefined,
      });
      setTickets(res.tickets);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Ticket Decomposition</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Feature description → ordered ticket list across FE / API / DB / tests / observability / rollout.
        </p>
      </header>

      <form onSubmit={submit} className="rounded-lg border border-slate-800 bg-slate-900/40 p-5 space-y-4">
        <label className="block text-sm">
          <span className="text-slate-400">Feature</span>
          <textarea
            value={feature}
            onChange={(e) => setFeature(e.target.value)}
            placeholder="Build per-workout-difficulty filters on the dashboard…"
            rows={4}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-400">Repo (optional, for graph context)</span>
          <input
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder="architect-self"
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm font-mono"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !feature.trim()}
          className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-1.5 text-sm font-medium"
        >
          {busy ? 'Decomposing…' : 'Decompose'}
        </button>
      </form>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {tickets && (
        <ol className="space-y-3">
          {tickets.map((t, i) => (
            <li
              key={i}
              className="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
            >
              <div className="flex items-center gap-3 text-xs uppercase tracking-wider">
                <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">{t.kind}</span>
                {t.depends_on.length > 0 && (
                  <span className="text-slate-500">depends on: {t.depends_on.join(', ')}</span>
                )}
              </div>
              <p className="mt-1 font-medium">{t.title}</p>
              <p className="mt-1 text-sm text-slate-300 whitespace-pre-wrap">{t.description}</p>
              {t.touches_qnames.length > 0 && (
                <p className="mt-2 text-xs font-mono text-slate-500">
                  touches: {t.touches_qnames.join(', ')}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

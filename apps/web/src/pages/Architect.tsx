import { useState } from 'react';
import { api, ApiError, type ArchitectureProposal } from '../lib/api';

export default function ArchitectPage() {
  const [requirement, setRequirement] = useState('');
  const [repo, setRepo] = useState('');
  const [proposal, setProposal] = useState<ArchitectureProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!requirement.trim()) return;
    setBusy(true);
    setError(null);
    setProposal(null);
    try {
      const res = await api.architect({ requirement, repo: repo.trim() || undefined });
      setProposal(res.proposal);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Architect</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Requirements → architecture. 7-node pipeline. Sonnet for the design steps;
          Opus for the final synthesize. Graph delta is staged in <code>decision_log</code>
          and shows up in Decisions for review.
        </p>
      </header>

      <form onSubmit={submit} className="rounded-lg border border-slate-800 bg-slate-900/40 p-5 space-y-4">
        <label className="block text-sm">
          <span className="text-slate-400">Requirement</span>
          <textarea
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
            placeholder="Build a scalable real-time chat system for 50k concurrent users with delivery receipts and offline sync."
            rows={5}
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
          disabled={busy || !requirement.trim()}
          className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-1.5 text-sm font-medium"
        >
          {busy ? 'Designing… (this runs 7 LLM steps)' : 'Design'}
        </button>
      </form>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {proposal && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
          <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
            <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-3">
              Architecture document
            </h2>
            <pre className="whitespace-pre-wrap text-sm text-slate-100 font-mono">
              {proposal.markdown}
            </pre>
          </section>
          <aside className="space-y-4">
            <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-2">Services</h2>
              <ul className="text-sm space-y-1">
                {proposal.services.map((s) => (
                  <li key={s.name}>
                    <span className="font-mono">{s.name}</span>{' '}
                    <span className="text-slate-500">[{s.layer}]</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-2">Tables</h2>
              <ul className="text-sm space-y-1">
                {proposal.tables.map((t) => (
                  <li key={t.name} className="font-mono">{t.name}</li>
                ))}
              </ul>
            </section>
            <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-2">
                Endpoints
              </h2>
              <ul className="text-sm space-y-1">
                {proposal.endpoints.map((e, i) => (
                  <li key={i} className="font-mono">
                    <span className="text-emerald-400">{e.method}</span> {e.path}
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <h2 className="text-xs uppercase tracking-wider text-slate-400 mb-2">
                Proposed delta
              </h2>
              <p className="text-sm text-slate-300">
                {proposal.graph_delta.nodes.length} nodes,{' '}
                {proposal.graph_delta.edges.length} edges staged for review.
              </p>
              <p className="text-xs text-slate-500 mt-2">
                Open the <em>Decisions</em> tab to approve and apply.
              </p>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}

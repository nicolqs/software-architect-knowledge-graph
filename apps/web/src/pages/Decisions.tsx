import { useEffect, useState, useCallback } from 'react';
import { ApiError, api, type Decision } from '../lib/api';

const STATUS_COLOR: Record<string, string> = {
  proposed: 'text-amber-400',
  approved: 'text-emerald-400',
  rejected: 'text-red-400',
  applied: 'text-sky-400',
};

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [filter, setFilter] = useState<string>('proposed');
  const [reviewer, setReviewer] = useState('me@local');
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await api.decisions({ status: filter || undefined });
      setDecisions(r.decisions);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [filter]);

  useEffect(() => {
    // Data-fetch on mount + filter change. The new react-hooks/set-state-in-
    // effect rule (plugin v7) flags this; the pattern is intentional.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function act(id: number, status: 'approved' | 'rejected', apply: boolean) {
    setBusyId(id);
    try {
      await api.reviewDecision(id, { status, reviewer, apply_now: apply });
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Decisions</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Every graph mutation an agent proposes lands here. Approve and apply to push
          into the live graph; reject to keep it as an audit trail.
        </p>
      </header>

      <div className="flex items-center gap-3 text-sm">
        <label className="text-slate-400">Status:</label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded bg-slate-800 border border-slate-700 px-2 py-1 text-sm"
        >
          <option value="">all</option>
          <option value="proposed">proposed</option>
          <option value="approved">approved</option>
          <option value="rejected">rejected</option>
          <option value="applied">applied</option>
        </select>
        <label className="text-slate-400">Reviewer:</label>
        <input
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          className="rounded bg-slate-800 border border-slate-700 px-2 py-1 text-sm font-mono w-48"
        />
        <button
          onClick={() => void load()}
          className="rounded bg-slate-700 hover:bg-slate-600 px-3 py-1 text-sm"
        >
          Reload
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {decisions.length === 0 ? (
        <p className="text-slate-400 text-sm">No proposals match this filter.</p>
      ) : (
        <ul className="space-y-2">
          {decisions.map((d) => (
            <li key={d.id} className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
              <div className="flex items-center gap-3 text-xs uppercase tracking-wider">
                <span className="font-mono text-slate-400">#{d.id}</span>
                <span className={STATUS_COLOR[d.status] ?? 'text-slate-300'}>{d.status}</span>
                <span className="text-slate-500">{d.agent}</span>
                <span className="text-slate-500">{d.action}</span>
                {d.repo && <span className="text-slate-500">repo: {d.repo}</span>}
              </div>
              {d.target_qname && (
                <p className="mt-1 font-mono text-sm text-slate-200">{d.target_qname}</p>
              )}
              <pre className="mt-2 text-xs text-slate-400 whitespace-pre-wrap font-mono bg-slate-950/50 rounded p-2 overflow-x-auto">
                {JSON.stringify(d.props, null, 2)}
              </pre>
              {d.status === 'proposed' && (
                <div className="mt-3 flex gap-2">
                  <button
                    disabled={busyId === d.id}
                    onClick={() => void act(d.id, 'approved', true)}
                    className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 px-3 py-1 text-xs"
                  >
                    Approve & apply
                  </button>
                  <button
                    disabled={busyId === d.id}
                    onClick={() => void act(d.id, 'approved', false)}
                    className="rounded bg-emerald-700/60 hover:bg-emerald-700 disabled:bg-slate-700 px-3 py-1 text-xs"
                  >
                    Approve (don't apply)
                  </button>
                  <button
                    disabled={busyId === d.id}
                    onClick={() => void act(d.id, 'rejected', false)}
                    className="rounded bg-red-700/60 hover:bg-red-700 disabled:bg-slate-700 px-3 py-1 text-xs"
                  >
                    Reject
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

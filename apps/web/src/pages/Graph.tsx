import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ApiError,
  api,
  type QnameSuggestion,
  type RepoSummary,
  type Subgraph,
} from '../lib/api';

const LABEL_COLOR: Record<string, string> = {
  Function: '#34d399',
  Class: '#60a5fa',
  Module: '#a78bfa',
  File: '#fbbf24',
  External: '#9ca3af',
  Repo: '#f472b6',
  Service: '#fb7185',
  API: '#22d3ee',
  DBTable: '#facc15',
};

function layoutSubgraph(sg: Subgraph): { nodes: Node[]; edges: Edge[] } {
  const center = { x: 400, y: 300 };
  const radius = 220;
  const ringNodes = sg.nodes.filter((n) => n.qname !== sg.qname);
  const angleStep = (Math.PI * 2) / Math.max(ringNodes.length, 1);
  const positions = new Map<string, { x: number; y: number }>();
  positions.set(sg.qname, center);
  ringNodes.forEach((n, i) => {
    positions.set(n.qname, {
      x: center.x + Math.cos(i * angleStep) * radius,
      y: center.y + Math.sin(i * angleStep) * radius,
    });
  });
  const nodes: Node[] = sg.nodes.map((n) => ({
    id: n.qname,
    data: {
      label: (
        <div className="text-xs">
          <div className="font-mono text-[10px] text-slate-200">
            {n.qname.split(/\.|::/).pop()}
          </div>
          <div className="text-[9px] text-slate-400 mt-0.5">{n.label}</div>
        </div>
      ),
    },
    position: positions.get(n.qname) ?? center,
    style: {
      background: '#1e293b',
      color: '#e2e8f0',
      border: `1.5px solid ${LABEL_COLOR[n.label] ?? '#64748b'}`,
      borderRadius: 6,
      padding: 6,
      width: 140,
    },
  }));
  const edges: Edge[] = sg.edges.map((e, i) => ({
    id: `${e.from_qname}->${e.to_qname}-${i}`,
    source: e.from_qname,
    target: e.to_qname,
    label: e.rel,
    labelStyle: { fill: '#94a3b8', fontSize: 9 },
    labelBgStyle: { fill: '#0f172a' },
    style: { stroke: '#475569', strokeWidth: 1 },
  }));
  return { nodes, edges };
}

export default function GraphPage() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [repo, setRepo] = useState('');
  const [qname, setQname] = useState('');
  const [depth, setDepth] = useState(1);
  const [suggestions, setSuggestions] = useState<QnameSuggestion[]>([]);
  const [sg, setSg] = useState<Subgraph | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.repos().then((r) => {
      setRepos(r);
      if (r.length && !repo) setRepo(r[0].name);
    });
  }, [repo]);

  const load = useCallback(
    async (targetRepo: string, targetQname: string, targetDepth: number) => {
      setBusy(true);
      setError(null);
      try {
        setSg(
          await api.subgraph({
            repo: targetRepo,
            qname: targetQname,
            depth: targetDepth,
          }),
        );
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  // On repo change (or first mount), fetch top qnames and auto-load the most-
  // called one so the canvas isn't empty when you arrive at this page.
  useEffect(() => {
    if (!repo) return;
    let cancelled = false;
    (async () => {
      try {
        const sugg = await api.qnames({ repo, limit: 50 });
        if (cancelled) return;
        setSuggestions(sugg);
        if (sugg.length > 0) {
          const first = sugg[0].qname;
          setQname(first);
          await load(repo, first, depth);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // We deliberately fire only on `repo` change. Re-running on `depth`
    // changes would replace the user's current view every time they bump
    // the slider — they can resubmit the form instead. TODO: race-protect
    // with a sequence number when we add multi-repo switching.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repo]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!repo || !qname.trim()) return;
    void load(repo, qname.trim(), depth);
  }

  const flow = useMemo(
    () => (sg ? layoutSubgraph(sg) : { nodes: [], edges: [] }),
    [sg],
  );

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Graph viewer</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Subgraph around a chosen qname. Up to 3 hops; capped per layer.
          The default shows the most-called function in the repo — type to filter.
        </p>
      </header>

      <form
        onSubmit={onSubmit}
        className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 grid grid-cols-[200px_1fr_120px_auto] gap-3 items-end"
      >
        <label className="block text-sm">
          <span className="text-slate-400">Repo</span>
          <select
            value={repo}
            onChange={(e) => {
              // Don't clear qname here — the repo-change useEffect will set
              // it to the new top suggestion. Clearing first causes a flicker.
              setRepo(e.target.value);
              setSg(null);
            }}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm"
          >
            {repos.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-slate-400">
            qname{' '}
            <span className="text-slate-600">
              (pick from list — sorted by fan-in)
            </span>
          </span>
          <input
            list="qname-suggestions"
            value={qname}
            onChange={(e) => setQname(e.target.value)}
            placeholder="start typing or pick from the dropdown…"
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm font-mono"
          />
          <datalist id="qname-suggestions">
            {suggestions.map((s) => (
              <option key={s.qname} value={s.qname}>
                {s.label} · {s.callers} caller{s.callers === 1 ? '' : 's'}
              </option>
            ))}
          </datalist>
        </label>
        <label className="block text-sm">
          <span className="text-slate-400">Depth</span>
          <select
            value={depth}
            onChange={(e) => setDepth(parseInt(e.target.value))}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm"
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={busy || !qname.trim()}
          className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-1.5 text-sm font-medium"
        >
          {busy ? '…' : 'Load'}
        </button>
      </form>

      {suggestions.length > 0 && (
        <div className="text-xs text-slate-500">
          Top callees:{' '}
          {suggestions.slice(0, 5).map((s, i) => (
            <span key={s.qname}>
              <button
                type="button"
                className="font-mono hover:text-emerald-400 hover:underline"
                onClick={() => {
                  setQname(s.qname);
                  void load(repo, s.qname, depth);
                }}
              >
                {s.qname.split(/\.|::/).pop()}
              </button>
              <span className="text-slate-700">({s.callers})</span>
              {i < 4 && i < suggestions.length - 1 ? ' · ' : ''}
            </span>
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-slate-800 bg-slate-950 h-[560px]">
        <ReactFlow nodes={flow.nodes} edges={flow.edges} fitView>
          <Background color="#1e293b" gap={20} />
          <Controls className="!bg-slate-900 !border-slate-700" />
        </ReactFlow>
      </div>

      {sg && (
        <p className="text-xs text-slate-500">
          {sg.nodes.length} nodes, {sg.edges.length} edges around{' '}
          <span className="font-mono text-slate-300">{sg.qname}</span> at depth{' '}
          {sg.depth}.
        </p>
      )}
    </div>
  );
}

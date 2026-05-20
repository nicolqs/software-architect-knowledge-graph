import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, api, type RepoSummary, type Subgraph } from '../lib/api';

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
  // Simple radial layout: root in the center, neighbors in a ring.
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
  const [sg, setSg] = useState<Subgraph | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.repos().then((r) => {
      setRepos(r);
      if (r.length && !repo) setRepo(r[0].name);
    });
  }, [repo]);

  async function load(e: React.FormEvent) {
    e.preventDefault();
    if (!repo || !qname.trim()) return;
    setBusy(true);
    setError(null);
    setSg(null);
    try {
      setSg(await api.subgraph({ repo, qname: qname.trim(), depth }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const flow = useMemo(() => (sg ? layoutSubgraph(sg) : { nodes: [], edges: [] }), [sg]);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Graph viewer</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Subgraph around a chosen qname. Up to 3 hops; capped per layer.
        </p>
      </header>

      <form onSubmit={load} className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 grid grid-cols-[200px_1fr_120px_auto] gap-3 items-end">
        <label className="block text-sm">
          <span className="text-slate-400">Repo</span>
          <select
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm"
          >
            {repos.map((r) => (
              <option key={r.name} value={r.name}>{r.name}</option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-slate-400">qname</span>
          <input
            value={qname}
            onChange={(e) => setQname(e.target.value)}
            placeholder="apps.api.src.architect.ingest.pipeline.run_ingest"
            className="mt-1 w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm font-mono"
          />
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
          <span className="font-mono text-slate-300">{sg.qname}</span> at depth {sg.depth}.
        </p>
      )}
    </div>
  );
}

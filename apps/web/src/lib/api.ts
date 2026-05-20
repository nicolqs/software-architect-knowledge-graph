// Thin typed API client. Types mirror the Pydantic schemas in apps/api.
// We hand-maintain them in v1; M5 swaps to openapi-typescript codegen.

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // body wasn't JSON; keep statusText.
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// ---- Schemas (mirror Pydantic in apps/api) -------------------------------

export type Health = {
  status: 'ok' | 'degraded';
  version: string;
  neo4j: boolean;
  postgres: boolean;
};

export type RepoSummary = {
  name: string;
  files: number;
  functions: number;
  classes: number;
  modules: number;
};

export type GraphNode = { qname: string; label: string };
export type GraphEdge = { from_qname: string; to_qname: string; rel: string };

export type Subgraph = {
  repo: string;
  qname: string;
  depth: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type ReviewFinding = {
  severity: 'critical' | 'important' | 'advisory';
  rule: string;
  message: string;
  qname?: string;
  file_path?: string;
  line?: number;
};

export type ReviewerResponse = {
  repo: string;
  findings: ReviewFinding[];
  summary: { critical: number; important: number; advisory: number };
};

export type RefactorItem = {
  kind: 'dead_code' | 'high_coupling' | 'duplicate_logic';
  qname: string;
  title: string;
  rationale: string;
  risk: 'low' | 'medium' | 'high';
  blast_radius: number;
  file_path?: string;
  line?: number;
};

export type RefactorResponse = {
  repo: string;
  items: RefactorItem[];
  summary: Record<string, number>;
};

export type Ticket = {
  kind: 'FE' | 'API' | 'DB' | 'tests' | 'observability' | 'rollout' | 'docs';
  title: string;
  description: string;
  depends_on: string[];
  touches_qnames: string[];
};

export type TicketsResponse = { tickets: Ticket[]; thread_id: string };

export type EchoResponse = { response: string; thread_id: string };

export type ProposedService = {
  name: string;
  layer: 'edge' | 'api' | 'domain' | 'data' | 'infra';
  responsibilities: string[];
  depends_on: string[];
};
export type ProposedColumn = {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
};
export type ProposedTable = {
  name: string;
  owned_by_service: string;
  columns: ProposedColumn[];
  indexes: string[];
  foreign_keys: string[];
};
export type ProposedEndpoint = {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: string;
  summary: string;
  owned_by_service: string;
  request_shape: string;
  response_shape: string;
};
export type NfrConcern = {
  area: 'scaling' | 'observability' | 'security' | 'reliability' | 'cost';
  concern: string;
  mitigation: string;
};
export type ProposedGraphDelta = {
  nodes: { label: string; qname: string; props?: Record<string, unknown> }[];
  edges: {
    from_qname: string;
    to_qname: string;
    rel_type: string;
    props?: Record<string, unknown>;
  }[];
};
export type ArchitectureProposal = {
  services: ProposedService[];
  tables: ProposedTable[];
  endpoints: ProposedEndpoint[];
  nfrs: NfrConcern[];
  markdown: string;
  graph_delta: ProposedGraphDelta;
};
export type ArchitectResponse = { proposal: ArchitectureProposal; thread_id: string };

export type Decision = {
  id: number;
  agent: string;
  action: string;
  repo: string | null;
  target_qname: string | null;
  props: Record<string, unknown>;
  status: string;
};

// ---- Endpoints -----------------------------------------------------------

export const api = {
  health: () => request<Health>('/health'),
  repos: () => request<RepoSummary[]>('/graph/repos'),
  subgraph: (params: { repo: string; qname: string; depth?: number }) =>
    request<Subgraph>(
      `/graph/subgraph?repo=${encodeURIComponent(params.repo)}&qname=${encodeURIComponent(params.qname)}&depth=${params.depth ?? 1}`,
    ),

  echo: (body: { message: string; thread_id?: string }) =>
    request<EchoResponse>('/agents/echo', { method: 'POST', body: JSON.stringify(body) }),
  tickets: (body: {
    feature: string;
    repo?: string;
    target_qname?: string;
    thread_id?: string;
  }) =>
    request<TicketsResponse>('/agents/tickets', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  architect: (body: { requirement: string; repo?: string; thread_id?: string }) =>
    request<ArchitectResponse>('/agents/architect', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  reviewer: (body: { repo: string; changed_files: string[] }) =>
    request<ReviewerResponse>('/agents/reviewer', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  refactor: (body: { repo: string }) =>
    request<RefactorResponse>('/agents/refactor', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  decisions: (params?: { status?: string; repo?: string; agent?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.repo) qs.set('repo', params.repo);
    if (params?.agent) qs.set('agent', params.agent);
    const suffix = qs.toString();
    return request<{ decisions: Decision[] }>(
      `/decisions${suffix ? `?${suffix}` : ''}`,
    );
  },
  reviewDecision: (
    id: number,
    body: { status: 'approved' | 'rejected'; reviewer: string; apply_now?: boolean },
  ) =>
    request<{ id: number; new_status: string; applied: boolean }>(
      `/decisions/${id}/review`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
};

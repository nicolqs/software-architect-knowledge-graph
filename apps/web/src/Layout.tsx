import { NavLink, Outlet } from 'react-router-dom';

const NAV: { to: string; label: string; subtitle?: string }[] = [
  { to: '/', label: 'Status' },
  { to: '/graph', label: 'Graph', subtitle: 'Browse the ingested repo' },
  { to: '/agents/architect', label: 'Architect', subtitle: 'Requirements → architecture' },
  { to: '/agents/tickets', label: 'Tickets', subtitle: 'Decompose a feature' },
  { to: '/agents/reviewer', label: 'Reviewer', subtitle: 'Audit a PR' },
  { to: '/agents/refactor', label: 'Refactor', subtitle: 'Plan a cleanup' },
  { to: '/agents/echo', label: 'Echo', subtitle: 'Framework smoke test' },
  { to: '/decisions', label: 'Decisions', subtitle: 'Approve / reject proposals' },
];

export default function Layout() {
  return (
    <div className="grid grid-cols-[240px_1fr] min-h-screen">
      <aside className="bg-slate-900/60 border-r border-slate-800 px-3 py-5">
        <header className="px-3 mb-6">
          <div className="text-sm uppercase tracking-wider text-slate-500">AI Autonomous</div>
          <div className="text-base font-semibold">Software Architect</div>
        </header>
        <nav className="space-y-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 text-sm leading-tight ${
                  isActive
                    ? 'bg-slate-800 text-slate-50'
                    : 'text-slate-300 hover:bg-slate-800/60 hover:text-slate-100'
                }`
              }
            >
              <div>{n.label}</div>
              {n.subtitle && <div className="text-[11px] text-slate-500">{n.subtitle}</div>}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="px-8 py-6 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  );
}

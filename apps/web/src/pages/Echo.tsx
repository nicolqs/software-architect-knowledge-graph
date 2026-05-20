import { useState } from 'react';
import { api, ApiError, type EchoResponse } from '../lib/api';

export default function EchoPage() {
  const [message, setMessage] = useState('');
  const [threadId, setThreadId] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<{ role: 'user' | 'agent'; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    setBusy(true);
    setError(null);
    const userText = message;
    setHistory((h) => [...h, { role: 'user', text: userText }]);
    setMessage('');
    try {
      const res: EchoResponse = await api.echo({ message: userText, thread_id: threadId });
      setThreadId(res.thread_id);
      setHistory((h) => [...h, { role: 'agent', text: res.response }]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Echo</h1>
        <p className="text-slate-400 mt-1 text-sm">
          Framework smoke-test agent. Verifies budget check → LLM call → cost_log → checkpointer.
          Thread persists across turns via thread_id.
        </p>
      </header>

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 space-y-3 min-h-[160px]">
        {history.length === 0 && (
          <p className="text-slate-500 text-sm">Send a message to start.</p>
        )}
        {history.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div
              className={`inline-block max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                m.role === 'user'
                  ? 'bg-emerald-900/40 text-emerald-100'
                  : 'bg-slate-800 text-slate-100'
              }`}
            >
              {m.text}
            </div>
          </div>
        ))}
      </section>

      <form onSubmit={send} className="flex gap-2">
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Say hello…"
          disabled={busy}
          className="flex-1 rounded bg-slate-800 border border-slate-700 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !message.trim()}
          className="rounded bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-2 text-sm font-medium"
        >
          {busy ? '…' : 'Send'}
        </button>
      </form>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {threadId && (
        <div className="text-xs text-slate-500 font-mono">thread_id: {threadId}</div>
      )}
    </div>
  );
}

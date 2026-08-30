'use client';

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  FileText,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

type RuntimeCheck = { name: string; status: 'pass' | 'fail' | 'skip'; detail: string };
type Health = { ready: boolean; environment: string; checks: RuntimeCheck[] };
type Brief = {
  status: string;
  sections: Record<string, string>;
  cited_evidence_ids: string[];
  pending_approval_ids: string[];
};
type RunResult = {
  run_id: string;
  status: 'allowed' | 'approval_required' | 'denied' | 'failed';
  safe_error?: string | null;
  brief?: Brief | null;
};

const sectionOrder = [
  'Deal Snapshot',
  'Executive Summary',
  'Buyer Goals and Business Drivers',
  'Stakeholder Map',
  'Negotiation State',
  'Recommended Next Actions',
  'Missing Information',
  'Source Evidence',
  'Confidence and Review Warnings',
];

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<RunResult | null>(null);
  const [opportunityId, setOpportunityId] = useState('OPP-1001');
  const [requesterId, setRequesterId] = useState('USR-5001');
  const [request, setRequest] = useState(
    'Generate an internal Strategic Deal Intelligence Brief.',
  );

  async function checkHealth(includeModel = false) {
    setChecking(true);
    setError('');
    try {
      const response = await fetch(`/api/health?include_model=${includeModel}`);
      if (!response.ok) throw new Error('Readiness check failed');
      setHealth(await response.json());
    } catch {
      setError('The local workflow service is not reachable. Start the Python web server.');
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    let active = true;
    fetch('/api/health?include_model=false')
      .then((response) => {
        if (!response.ok) throw new Error('Readiness check failed');
        return response.json() as Promise<Health>;
      })
      .then((report) => {
        if (active) setHealth(report);
      })
      .catch(() => {
        if (active) {
          setError('The local workflow service is not reachable. Start the Python web server.');
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: { preventDefault: () => void }) {
    event.preventDefault();
    setRunning(true);
    setError('');
    setResult(null);
    try {
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          opportunity_id: opportunityId,
          requester_id: requesterId,
          user_input: request,
        }),
      });
      if (!response.ok) throw new Error('Run failed');
      setResult(await response.json());
    } catch {
      setError('The run could not be completed. Check readiness and server logs.');
    } finally {
      setRunning(false);
    }
  }

  const passed = health?.checks.filter((check) => check.status === 'pass').length ?? 0;

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-white/8 bg-[#07191d] text-white">
        <div className="mx-auto flex max-w-[1480px] items-center justify-between px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-[#20c997] text-[#04251f]">
              <Activity className="size-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#87d8c2]">
                Strategic agent
              </p>
              <h1 className="text-lg font-semibold tracking-tight">Deal Intelligence Console</h1>
            </div>
          </div>
          <Badge variant="outline" className="border-white/15 bg-white/5 text-[#c9f4e8]">
            <span className="size-1.5 rounded-full bg-[#20c997]" /> Local only
          </Badge>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1480px] gap-5 px-5 py-5 lg:grid-cols-[390px_minmax(0,1fr)] lg:px-8 lg:py-8">
        <aside className="space-y-5">
          <Card className="border-0 bg-[#0b252a] text-white ring-0">
            <CardHeader className="border-b border-white/8">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-white">Runtime readiness</CardTitle>
                  <CardDescription className="text-[#8fb9b0]">
                    Evidence, storage, and model connectivity
                  </CardDescription>
                </div>
                <div className={`size-2.5 rounded-full ${health?.ready ? 'bg-[#20c997]' : 'bg-amber-400'}`} />
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-[#8fb9b0]">Checks passed</span>
                <span className="font-mono text-[#c9f4e8]">{passed}/{health?.checks.length ?? '—'}</span>
              </div>
              <div className="space-y-2">
                {health?.checks.map((check) => (
                  <div key={check.name} className="flex items-start gap-2 rounded-lg bg-white/[0.045] px-3 py-2.5" title={check.detail}>
                    {check.status === 'pass' ? (
                      <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-[#20c997]" />
                    ) : check.status === 'fail' ? (
                      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-400" />
                    ) : (
                      <Database className="mt-0.5 size-4 shrink-0 text-[#8fb9b0]" />
                    )}
                    <div className="min-w-0">
                      <p className="text-xs font-medium capitalize">{check.name.replaceAll('_', ' ')}</p>
                      <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-[#8fb9b0]">{check.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
              <Button type="button" variant="outline" className="w-full border-white/12 bg-white/5 text-white hover:bg-white/10 hover:text-white" onClick={() => void checkHealth(true)} disabled={checking}>
                <RefreshCw className={checking ? 'animate-spin' : ''} />
                {checking ? 'Checking…' : 'Check model connection'}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>New intelligence run</CardTitle>
              <CardDescription>Scope the request. Authorization is enforced before evidence retrieval.</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={submit}>
                <div className="grid grid-cols-2 gap-3">
                  <label htmlFor="opportunity-id" className="space-y-1.5 text-xs font-medium">
                    Opportunity
                    <Input id="opportunity-id" value={opportunityId} onChange={(event) => setOpportunityId(event.target.value)} required pattern="OPP-[0-9]+" />
                  </label>
                  <label htmlFor="requester-id" className="space-y-1.5 text-xs font-medium">
                    Requester
                    <Input id="requester-id" value={requesterId} onChange={(event) => setRequesterId(event.target.value)} required pattern="USR-[0-9]+" />
                  </label>
                </div>
                <label htmlFor="analyst-request" className="block space-y-1.5 text-xs font-medium">
                  Analyst request
                  <Textarea id="analyst-request" className="min-h-28 resize-none" value={request} onChange={(event) => setRequest(event.target.value)} maxLength={2000} required />
                </label>
                <Button type="submit" size="lg" className="h-10 w-full bg-[#0b6655] hover:bg-[#084e42]" disabled={running}>
                  {running ? <LoaderCircle className="animate-spin" /> : <Play className="fill-current" />}
                  {running ? 'Analysts are running…' : 'Run three analysts'}
                </Button>
              </form>
            </CardContent>
          </Card>
        </aside>

        <section className="min-w-0">
          <Card className="min-h-[calc(100vh-140px)]">
            <CardHeader className="border-b bg-[#f7faf8] dark:bg-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2"><FileText className="size-4 text-[#0b6655]" /> Strategic Deal Brief</CardTitle>
                  <CardDescription>Validated output from all required analysts</CardDescription>
                </div>
                {result && <Badge variant={result.status === 'failed' ? 'destructive' : 'outline'} className="capitalize">{result.status.replaceAll('_', ' ')}</Badge>}
              </div>
            </CardHeader>
            <CardContent className="py-5">
              {error && <div role="alert" className="mb-5 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{error}</div>}
              {running && (
                <div className="grid min-h-[480px] place-items-center text-center">
                  <div><LoaderCircle className="mx-auto size-8 animate-spin text-[#0b6655]" /><h2 className="mt-4 font-semibold">Analysts are working concurrently</h2><p className="mt-1 max-w-sm text-sm text-muted-foreground">Commercial, buyer signal, and risk analysis must all finish before composition.</p></div>
                </div>
              )}
              {!running && !result && (
                <div className="grid min-h-[480px] place-items-center text-center">
                  <div className="max-w-md"><div className="mx-auto grid size-14 place-items-center rounded-2xl bg-[#e3f5ef] text-[#0b6655]"><ShieldCheck className="size-7" /></div><h2 className="mt-4 text-lg font-semibold">Ready for a scoped run</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">The console checks authorization, retrieves permission-filtered FTS5 evidence, runs three analysts in parallel, and only composes a fully validated brief.</p></div>
                </div>
              )}
              {!running && result && !result.brief && (
                <div className="rounded-xl border border-dashed p-6"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Run {result.run_id}</p><h2 className="mt-2 text-lg font-semibold capitalize">{result.status.replaceAll('_', ' ')}</h2><p className="mt-2 text-sm text-muted-foreground">{result.safe_error ?? 'No brief was produced.'}</p></div>
              )}
              {!running && result?.brief && (
                <article className="mx-auto max-w-4xl">
                  <div className="mb-6 flex flex-wrap items-center gap-2 border-b pb-4 text-xs text-muted-foreground"><span className="font-mono">{result.run_id}</span><span>•</span><span>{result.brief.cited_evidence_ids.length} cited evidence records</span></div>
                  <div className="space-y-7">
                    {sectionOrder.map((section) => <section key={section}><h2 className="mb-2 text-xs font-bold uppercase tracking-[0.13em] text-[#0b6655]">{section}</h2><p className="whitespace-pre-wrap text-[15px] leading-7 text-[#263b3b]">{result.brief?.sections[section] || 'No supported information.'}</p></section>)}
                  </div>
                </article>
              )}
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}

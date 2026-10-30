import type { AssertionResult } from '../types/api'

export function JudgeEvidence({ assertions }: { assertions: AssertionResult[] | null }) {
  const judges = assertions?.filter((assertion) => assertion.evaluator === 'llm_judge') ?? []
  if (!judges.length) return null
  return <section aria-label="Semantic judgment" className="evidence-block">
    <h3>Semantic judgment</h3>
    <p>A model's assessment against the rubric. Review its explanation; this is not proof of safety.</p>
    {judges.map(({ index, outcome, code, evidence }) => <div key={index}>
      <p><strong>{outcome === 'errored' ? 'Judge could not evaluate' : `Score ${String(evidence.score ?? '—')}/100`}</strong>
        {' · '}{String(evidence.provider ?? 'Judge')} / {String(evidence.model ?? 'unavailable')}
        {' · '}{evidence.cache_hit ? 'Cached judgment — no new model call' : 'Fresh evaluation attempt'}</p>
      <p>{typeof evidence.explanation === 'string' ? evidence.explanation : code}</p>
      <p>Pass threshold: {String(evidence.pass_score ?? '—')}/100 · Judge time: {String(evidence.latency_ms ?? '—')} ms
        {' · '}Attempts: {String(evidence.attempts ?? 0)}</p>
      <p>Reported tokens: {String(evidence.input_tokens ?? 0)} input / {String(evidence.output_tokens ?? 0)} output
        {evidence.usage_complete !== true ? ' (usage incomplete)' : ''}
        {' · '}Estimated cost: {typeof evidence.estimated_cost_usd === 'number' ? `$${evidence.estimated_cost_usd.toFixed(6)}` : 'unavailable'}</p>
      {evidence.cache_hit === true && <p>Usage and cost above are for this cache lookup. Original-call details are in the evidence below.</p>}
    </div>)}
  </section>
}

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import type { Baseline, Comparison, EvaluationRun, HistoryAnalytics } from '../types/api'

export function HistoricalAnalysis({ run }: { run: EvaluationRun }) {
  const [baselines, setBaselines] = useState<Baseline[]>([])
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [history, setHistory] = useState<HistoryAnalytics | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    void api.listBaselines(run.target_application_id).then((items) => {
      if (active) setBaselines(items)
    }).catch((e: Error) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [run.target_application_id, refresh])

  useEffect(() => {
    setComparison(null)
    setHistory(null)
    setError('')
    if (!selected) return
    const controller = new AbortController()
    void Promise.all([
      api.compareEvaluation(run.id, Number(selected), controller.signal),
      api.getAnalytics(run.target_application_id, Number(selected), controller.signal),
    ]).then(([nextComparison, nextHistory]) => {
      if (!controller.signal.aborted) { setComparison(nextComparison); setHistory(nextHistory) }
    }).catch((e: Error) => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [run.id, run.target_application_id, selected, refresh])

  async function saveBaseline(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const saved = await api.createBaseline(run.target_application_id, run.id, name.trim())
      setName('')
      setRefresh((v) => v + 1)
      setSelected(String(saved.id))
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save baseline.') }
    finally { setSaving(false) }
  }

  return <section className="panel history-panel" aria-label="Historical analysis">
    <div className="panel__header"><div>
      <h2>Historical analysis</h2>
      <p>Version labels: {Object.entries(run.version_tags || {}).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(' · ') || 'Not supplied'}</p>
      <p>A baseline is a named reference to one completed run. Its name always refers to that same evidence.</p>
    </div></div>
    <div className="history-panel__body">
      {run.status === 'completed' && run.metrics?.coverage === 100 && run.metrics.evaluated > 0 && <form onSubmit={(event) => void saveBaseline(event)} className="history-controls">
        <label>Baseline name <input aria-label="Baseline name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. release-1" required /></label>
        <button className="button button--secondary" disabled={saving || !name.trim()}>{saving ? 'Saving…' : 'Save as baseline'}</button>
      </form>}
      <label>Compare with baseline <select aria-label="Compare with baseline" value={selected} onChange={(e) => setSelected(e.target.value)}>
        <option value="">Choose a baseline</option>
        {baselines.map((baseline) => <option key={baseline.id} value={baseline.id}>{baseline.name} · Run #{baseline.run_id}</option>)}
      </select></label>
      {baselines.length === 0 && <p>No baselines saved for this target.</p>}
      {error && <p role="alert">{error} <button onClick={() => setRefresh((v) => v + 1)}>Retry analysis</button></p>}
      {comparison && <div aria-live="polite">
        <h3>{comparison.compatible ? 'Comparable configuration' : 'Incompatible configuration'}</h3>
        <p>{comparison.compatible ? `${comparison.sample_sizes.paired_behavioral} paired behavioral checks. Weighted pass-rate change: ${comparison.effect.change_percentage_points ?? 'Not scored'} percentage points.` : 'The saved target, test, engine or scoring configuration differs, or historical provenance is missing. No regression verdict is assigned.'}</p>
        <p>{comparison.regressions.length} observed regressions · {comparison.improvements.length} improvements · {comparison.execution_errors.length} execution errors</p>
        <p>Observed regressions: {comparison.regressions.join(', ') || 'None'}</p>
        {comparison.flags.includes('incomplete_run') && <p>One or both runs are incomplete; the paired evidence is partial.</p>}
        <p>Added checks: {comparison.added_attacks.length} · Removed checks: {comparison.removed_attacks.length} · Coverage transitions: {comparison.coverage_changes.length}</p>
        <p>Paired mean latency change: {comparison.latency.paired_mean_change_ms === null ? 'No samples' : `${comparison.latency.paired_mean_change_ms} ms (${comparison.latency.paired_sample_size} pairs)`}.</p>
        <p>A single run is an observation, not statistical proof. Execution errors do not count as behavioral regressions.</p>
        <details><summary>Comparison evidence and category changes</summary><pre>{JSON.stringify(comparison, null, 2)}</pre></details>
      </div>}
      {history && <>
        <h3>Score, coverage and latency history</h3>
        <p>Latest {history.points.length} runs through #{history.through_run_id}. {history.truncated ? 'Earlier runs are outside this window.' : 'All runs in this window are shown.'} Scores describe these checks; they are not a security certification.</p>
        <div className="table-scroll"><table className="history-table"><thead><tr><th>Run</th><th>Configuration</th><th>Weighted pass</th><th>Security checks</th><th>Coverage</th><th>Errors</th><th>Mean latency (n)</th></tr></thead><tbody>
          {history.points.map((point) => <tr key={point.run_id}>
            <td><Link to={`/evaluations/${point.run_id}`}>#{point.run_id}</Link><br />{point.status}</td>
            <td>{point.compatible ? 'Compatible' : 'Different'}<br />{Object.values(point.versions || {}).filter(Boolean).join(' / ')}</td>
            <td>{point.metrics?.weighted_score ?? '—'}</td><td>{point.security_metrics?.weighted_score ?? '—'}</td>
            <td>{point.metrics?.coverage ?? '—'}</td><td>{point.metrics?.errored ?? '—'}</td>
            <td>{point.latency.mean_ms ?? '—'} ms ({point.latency.sample_size})</td>
          </tr>)}
        </tbody></table></div>
        <p>{history.repetition.policy}</p>
        {history.repetition.groups.map((group, index) => <p key={index}>
          {Object.values(group.versions).filter(Boolean).join(' / ')}: {group.status === 'insufficient_repeats' ? 'Insufficient repeats' : group.status === 'insufficient_behavioral_samples' ? 'Insufficient behavioral samples' : 'Descriptive repeated-run evidence'}.
          {' '}Repeated regressions: {group.repeated_regressions.join(', ') || 'None'}. Needs review: {group.needs_review.join(', ') || 'None'}.
        </p>)}
        <details><summary>Sample sizes and reproducible history window</summary><pre>{JSON.stringify(history, null, 2)}</pre></details>
      </>}
    </div>
  </section>
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Filter, Plus, Radar, Search } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState, TableSkeleton } from '../components/AsyncState'
import { PageHeader } from '../components/PageHeader'
import { RunTable } from '../components/RunTable'
import { api } from '../lib/api'
import { runTargetName } from '../lib/format'
import type { EvaluationRun, EvaluationStatus, TargetApplication } from '../types/api'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

type StatusFilter = 'all' | EvaluationStatus

export function EvaluationsPage() {
  useDocumentTitle('Evaluations')
  const [runs, setRuns] = useState<EvaluationRun[] | null>(null)
  const [targets, setTargets] = useState<TargetApplication[]>([])
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')

  const loadRuns = useCallback(async () => {
    setError('')
    try {
      const [evaluationData, targetData] = await Promise.all([api.listEvaluations(), api.listTargets()])
      setRuns(evaluationData)
      setTargets(targetData)
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load evaluations.')
    }
  }, [])

  useEffect(() => {
    void loadRuns()
  }, [loadRuns])

  const targetsById = useMemo(() => new Map(targets.map((target) => [target.id, target.name])), [targets])
  const filteredRuns = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return [...(runs || [])]
      .filter((run) => status === 'all' || run.status === status)
      .filter((run) => !normalizedQuery || runTargetName(run, targetsById).toLowerCase().includes(normalizedQuery) || String(run.id).includes(normalizedQuery))
      .sort((a, b) => new Date(b.started_at ?? b.created_at).getTime() - new Date(a.started_at ?? a.created_at).getTime())
  }, [query, runs, status, targetsById])

  return (
    <div className="page">
      <PageHeader
        eyebrow="Security runs"
        title="Evaluations"
        description="Review every adversarial test run across your registered targets."
        actions={<Link className="button button--primary" to="/targets"><Plus size={17} />New evaluation</Link>}
      />
      {error ? <ErrorState message={error} onRetry={() => void loadRuns()} /> : (
        <section className="panel">
          <div className="toolbar">
            <label className="search-field">
              <Search size={17} aria-hidden="true" />
              <span className="sr-only">Search evaluations</span>
              <input type="search" placeholder="Search target or run ID" value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <label className="filter-field">
              <Filter size={16} aria-hidden="true" />
              <span className="sr-only">Filter by status</span>
              <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)}>
                <option value="all">All statuses</option>
                <option value="completed">Completed</option>
                <option value="running">Running</option>
                <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
                <option value="pending">Pending</option>
              </select>
            </label>
          </div>
          {!runs ? <TableSkeleton rows={6} /> : filteredRuns.length === 0 ? (
            runs.length === 0 ? (
              <EmptyState icon={Radar} title="No evaluations yet" description="Choose a registered target and run the adversarial security suite." action={<Link className="button button--primary" to="/targets">Choose a target</Link>} />
            ) : (
              <EmptyState icon={Search} title="No matching evaluations" description="Try a different target name, run ID, or status filter." />
            )
          ) : <RunTable runs={filteredRuns} targetsById={targetsById} />}
        </section>
      )}
    </div>
  )
}

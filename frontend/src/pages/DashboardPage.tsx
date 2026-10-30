import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowRight, CheckCircle2, Plus, Radar, ServerCog, Shield, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState, TableSkeleton } from '../components/AsyncState'
import { PageHeader } from '../components/PageHeader'
import { RunTable } from '../components/RunTable'
import { formatScore, scoreTone } from '../lib/format'
import { api } from '../lib/api'
import type { EvaluationRun, TargetApplication } from '../types/api'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

interface DashboardData {
  targets: TargetApplication[]
  evaluations: EvaluationRun[]
}

export function DashboardPage() {
  useDocumentTitle('Overview')
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')

  const loadDashboard = useCallback(async () => {
    setError('')
    try {
      const [targets, evaluations] = await Promise.all([api.listTargets(), api.listEvaluations()])
      setData({ targets, evaluations })
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load the dashboard.')
    }
  }, [])

  useEffect(() => {
    void loadDashboard()
  }, [loadDashboard])

  const completedRuns = data?.evaluations.filter((run) => run.status === 'completed' && run.total_tests > 0 && (!run.metrics || run.metrics.evaluated > 0)) || []
  const averageScore = completedRuns.length
    ? completedRuns.reduce((sum, run) => sum + (run.score || 0), 0) / completedRuns.length
    : null
  const recentRuns = useMemo(
    () =>
      [...(data?.evaluations || [])]
        .sort((a, b) => new Date(b.started_at ?? b.created_at).getTime() - new Date(a.started_at ?? a.created_at).getTime())
        .slice(0, 5),
    [data?.evaluations],
  )
  const targetsById = useMemo(
    () => new Map(data?.targets.map((target) => [target.id, target.name]) || []),
    [data?.targets],
  )

  return (
    <div className="page page--dashboard">
      <PageHeader
        eyebrow="Security posture"
        title="Overview"
        description="See how your AI applications behave under adversarial pressure."
        actions={
          <Link className="button button--primary" to="/targets/new">
            <Plus size={17} aria-hidden="true" />
            Register target
          </Link>
        }
      />

      {error ? (
        <ErrorState message={error} onRetry={() => void loadDashboard()} />
      ) : (
        <>
          <section className="stat-grid" aria-label="Workspace summary">
            <article className="stat-card">
              <span className="stat-card__icon stat-card__icon--blue" aria-hidden="true"><ServerCog size={20} /></span>
              <div>
                <span className="stat-card__label">Registered targets</span>
                <strong>{data ? data.targets.length : <span className="skeleton skeleton--number" />}</strong>
              </div>
              <Link to="/targets" aria-label="View targets"><ArrowRight size={17} /></Link>
            </article>
            <article className="stat-card">
              <span className="stat-card__icon stat-card__icon--violet" aria-hidden="true"><Radar size={20} /></span>
              <div>
                <span className="stat-card__label">Total evaluations</span>
                <strong>{data ? data.evaluations.length : <span className="skeleton skeleton--number" />}</strong>
              </div>
              <Link to="/evaluations" aria-label="View evaluations"><ArrowRight size={17} /></Link>
            </article>
            <article className="stat-card">
              <span className="stat-card__icon stat-card__icon--green" aria-hidden="true"><Shield size={20} /></span>
              <div>
                <span className="stat-card__label">Average original pass rate</span>
                <strong className={`score-text score-text--${scoreTone(averageScore)}`}>
                  {data ? formatScore(averageScore) : <span className="skeleton skeleton--number" />}
                </strong>
              </div>
              <span className="stat-card__context">Completed runs</span>
            </article>
            <article className="stat-card">
              <span className="stat-card__icon stat-card__icon--amber" aria-hidden="true"><CheckCircle2 size={20} /></span>
              <div>
                <span className="stat-card__label">Tests passed</span>
                <strong>
                  {data ? data.evaluations.reduce((sum, run) => sum + run.passed_tests, 0) : <span className="skeleton skeleton--number" />}
                </strong>
              </div>
              <span className="stat-card__context">All time</span>
            </article>
          </section>

          {data && data.targets.length === 0 ? (
            <section className="onboarding-card">
              <div className="onboarding-card__copy">
                <span className="onboarding-card__icon" aria-hidden="true"><Sparkles size={23} /></span>
                <p className="eyebrow">Start here</p>
                <h2>Run your first security evaluation</h2>
                <p>Connect an AI endpoint, add fake protected values, then let Sentinel probe it with deterministic adversarial tests.</p>
                <Link className="button button--primary" to="/targets/new">
                  Register your first target <ArrowRight size={16} />
                </Link>
              </div>
              <ol className="onboarding-steps">
                <li><span>1</span><div><strong>Register</strong><small>Configure the target API</small></div></li>
                <li><span>2</span><div><strong>Protect</strong><small>Add values that must not leak</small></div></li>
                <li><span>3</span><div><strong>Evaluate</strong><small>Review actionable findings</small></div></li>
              </ol>
            </section>
          ) : (
            <section className="panel">
              <div className="panel__header">
                <div>
                  <h2>Recent evaluations</h2>
                  <p>Your latest security and reliability test runs.</p>
                </div>
                {recentRuns.length > 0 && <Link className="text-link" to="/evaluations">View all <ArrowRight size={15} /></Link>}
              </div>
              {!data ? (
                <TableSkeleton />
              ) : recentRuns.length === 0 ? (
                <EmptyState
                  icon={Radar}
                  title="No evaluations yet"
                  description="Run an evaluation from a registered target to see its security posture here."
                  action={<Link className="button button--secondary" to="/targets">Choose a target</Link>}
                />
              ) : (
                <RunTable runs={recentRuns} targetsById={targetsById} />
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}

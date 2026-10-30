import { useCallback, useEffect, useState } from 'react'
import { Braces, Edit3, KeyRound, Plus, ServerCog, ShieldCheck, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState, TableSkeleton } from '../components/AsyncState'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { PageHeader } from '../components/PageHeader'
import { RunEvaluationButton } from '../components/RunEvaluationButton'
import { api } from '../lib/api'
import { formatRelativeTime } from '../lib/format'
import type { TargetApplication } from '../types/api'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function TargetsPage() {
  useDocumentTitle('Targets')
  const [targets, setTargets] = useState<TargetApplication[] | null>(null)
  const [error, setError] = useState('')
  const [runError, setRunError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<TargetApplication | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadTargets = useCallback(async () => {
    setError('')
    try {
      setTargets(await api.listTargets())
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load targets.')
    }
  }, [])

  useEffect(() => {
    void loadTargets()
  }, [loadTargets])

  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    setError('')
    try {
      await api.deleteTarget(deleteTarget.id)
      setTargets((current) => current?.filter((target) => target.id !== deleteTarget.id) || [])
      setDeleteTarget(null)
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete the target.')
      setDeleteTarget(null)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Attack surface"
        title="Targets"
        description="AI application endpoints configured for repeatable security testing."
        actions={<Link className="button button--primary" to="/targets/new"><Plus size={17} />Register target</Link>}
      />

      {error && <ErrorState message={error} onRetry={() => void loadTargets()} />}
      {runError && <div className="inline-alert inline-alert--error" role="alert">{runError}</div>}

      {!targets && !error ? (
        <section className="panel"><TableSkeleton rows={3} /></section>
      ) : targets?.length === 0 ? (
        <section className="panel">
          <EmptyState
            icon={ServerCog}
            title="No targets registered"
            description="Add an AI application's HTTP endpoint to begin testing it for prompt injection, leakage, and reliability failures."
            action={<Link className="button button--primary" to="/targets/new"><Plus size={16} />Register target</Link>}
          />
        </section>
      ) : targets && targets.length > 0 ? (
        <div className="target-grid">
          {targets.map((target) => (
            <article className="target-card" key={target.id}>
              <div className="target-card__top">
                <span className="target-card__icon" aria-hidden="true"><ServerCog size={21} /></span>
                <div className="target-card__identity">
                  <Link to={`/targets/${target.id}`}>{target.name}</Link>
                  <span>Added {formatRelativeTime(target.created_at)}</span>
                </div>
                <span className="method-badge">{target.http_method}</span>
              </div>

              <div className="endpoint-block">
                <span>Endpoint</span>
                <code title={target.endpoint_url}>{target.endpoint_url}</code>
              </div>

              <dl className="target-card__meta">
                <div>
                  <dt><Braces size={14} aria-hidden="true" /> Prompt field</dt>
                  <dd>{target.prompt_field}</dd>
                </div>
                <div>
                  <dt><ShieldCheck size={14} aria-hidden="true" /> Response field</dt>
                  <dd>{target.response_field}</dd>
                </div>
                <div>
                  <dt><KeyRound size={14} aria-hidden="true" /> API key</dt>
                  <dd>{target.has_api_key ? 'Configured' : 'Not required'}</dd>
                </div>
              </dl>

              <div className="target-card__actions">
                <RunEvaluationButton targetId={target.id} compact onError={setRunError} />
                <Link className="icon-button" to={`/targets/${target.id}/edit`} aria-label={`Edit ${target.name}`}><Edit3 size={17} /></Link>
                <button className="icon-button icon-button--danger" type="button" onClick={() => setDeleteTarget(target)} aria-label={`Delete ${target.name}`}><Trash2 size={17} /></button>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete target?"
        description={`This will permanently remove ${deleteTarget?.name || 'this target'} and all its protected values, evaluation history, and test results. This action cannot be undone.`}
        confirmLabel="Delete target"
        busy={deleting}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void handleDelete()}
      />
    </div>
  )
}

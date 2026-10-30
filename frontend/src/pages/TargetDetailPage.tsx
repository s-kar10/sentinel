import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  Braces,
  Clock3,
  Edit3,
  KeyRound,
  LockKeyhole,
  Plus,
  Radar,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { EmptyState, ErrorState, PageLoader } from '../components/AsyncState'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { PageHeader } from '../components/PageHeader'
import { RunEvaluationButton } from '../components/RunEvaluationButton'
import { RunTable } from '../components/RunTable'
import { api } from '../lib/api'
import { formatDateTime } from '../lib/format'
import type { EvaluationRun, ProtectedValue, TargetApplication } from '../types/api'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function TargetDetailPage() {
  const { targetId } = useParams()
  const id = Number(targetId)
  const navigate = useNavigate()
  const [target, setTarget] = useState<TargetApplication | null>(null)
  const [protectedValues, setProtectedValues] = useState<ProtectedValue[]>([])
  const [evaluations, setEvaluations] = useState<EvaluationRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [runError, setRunError] = useState('')
  const [protectedError, setProtectedError] = useState('')
  const [valueName, setValueName] = useState('')
  const [value, setValue] = useState('')
  const [addingValue, setAddingValue] = useState(false)
  const [deleteValue, setDeleteValue] = useState<ProtectedValue | null>(null)
  const [deleteTargetOpen, setDeleteTargetOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useDocumentTitle(target?.name || 'Target')

  const loadTarget = useCallback(async () => {
    if (!Number.isInteger(id)) {
      setError('This target ID is not valid.')
      setLoading(false)
      return
    }
    setError('')
    try {
      const [targetData, valuesData, allEvaluations] = await Promise.all([
        api.getTarget(id),
        api.listProtectedValues(id),
        api.listEvaluations(),
      ])
      setTarget(targetData)
      setProtectedValues(valuesData)
      setEvaluations(
        allEvaluations
          .filter((run) => run.target_application_id === id)
          .sort((a, b) => new Date(b.started_at ?? b.created_at).getTime() - new Date(a.started_at ?? a.created_at).getTime()),
      )
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load this target.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void loadTarget()
  }, [loadTarget])

  const targetsById = useMemo(() => new Map(target ? [[target.id, target.name]] : []), [target])

  async function handleAddValue(event: FormEvent) {
    event.preventDefault()
    if (!valueName.trim() || !value.trim()) {
      setProtectedError('Enter both a label and a protected value.')
      return
    }
    setAddingValue(true)
    setProtectedError('')
    try {
      const created = await api.createProtectedValue(id, { name: valueName.trim(), value: value.trim() })
      setProtectedValues((current) => [...current, created])
      setValueName('')
      setValue('')
    } catch (addError) {
      setProtectedError(addError instanceof Error ? addError.message : 'Unable to add the protected value.')
    } finally {
      setAddingValue(false)
    }
  }

  async function handleDeleteValue() {
    if (!deleteValue) return
    setDeleting(true)
    setProtectedError('')
    try {
      await api.deleteProtectedValue(deleteValue.id)
      setProtectedValues((current) => current.filter((item) => item.id !== deleteValue.id))
      setDeleteValue(null)
    } catch (deleteError) {
      setProtectedError(deleteError instanceof Error ? deleteError.message : 'Unable to remove the protected value.')
      setDeleteValue(null)
    } finally {
      setDeleting(false)
    }
  }

  async function handleDeleteTarget() {
    setDeleting(true)
    try {
      await api.deleteTarget(id)
      navigate('/targets', { replace: true })
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete this target.')
      setDeleteTargetOpen(false)
      setDeleting(false)
    }
  }

  if (loading) return <div className="page"><PageLoader label="Loading target" /></div>
  if (error || !target) {
    return <div className="page"><ErrorState title="Target unavailable" message={error || 'This target could not be found.'} onRetry={() => void loadTarget()} /></div>
  }

  return (
    <div className="page">
      <Link className="back-link" to="/targets"><ArrowLeft size={16} />All targets</Link>
      <PageHeader
        eyebrow="Registered target"
        title={target.name}
        description="Manage the endpoint contract, protected values, and evaluation history."
        actions={
          <>
            <Link className="button button--secondary" to={`/targets/${id}/edit`}><Edit3 size={16} />Edit</Link>
            <RunEvaluationButton targetId={id} onError={setRunError} />
          </>
        }
      />
      {runError && <div className="inline-alert inline-alert--error" role="alert">{runError}</div>}

      <section className="target-summary-grid">
        <article className="connection-card">
          <div className="section-title-row">
            <div><p className="eyebrow">Connection</p><h2>API contract</h2></div>
            <span className="method-badge">{target.http_method}</span>
          </div>
          <div className="endpoint-block endpoint-block--large"><span>Endpoint</span><code>{target.endpoint_url}</code></div>
          <dl className="detail-list">
            <div><dt><Braces size={15} />Prompt path</dt><dd><code>{target.prompt_field}</code></dd></div>
            <div><dt><ShieldCheck size={15} />Response path</dt><dd><code>{target.response_field}</code></dd></div>
            <div><dt><KeyRound size={15} />Authorization</dt><dd>{target.has_api_key ? 'API key configured' : 'No API key'}</dd></div>
            <div><dt><Clock3 size={15} />Last updated</dt><dd>{formatDateTime(target.updated_at)}</dd></div>
          </dl>
        </article>
        <article className="template-card">
          <div className="section-title-row"><div><p className="eyebrow">Payload</p><h2>Request template</h2></div><Braces size={19} /></div>
          <pre><code>{JSON.stringify(target.request_template, null, 2)}</code></pre>
          <p>Sentinel inserts each adversarial prompt at <code>{target.prompt_field}</code>.</p>
        </article>
      </section>

      <section className="panel protected-panel">
        <div className="panel__header">
          <div><h2>Protected values</h2><p>Fake secrets or identifiers that must never appear in target responses.</p></div>
          <span className="count-badge">{protectedValues.length}</span>
        </div>
        {protectedError && <div className="inline-alert inline-alert--error" role="alert">{protectedError}</div>}
        <form className="protected-form" onSubmit={handleAddValue}>
          <div className="field">
            <label htmlFor="value-name">Label</label>
            <input id="value-name" value={valueName} onChange={(event) => setValueName(event.target.value)} placeholder="Demo customer ID" />
          </div>
          <div className="field">
            <label htmlFor="protected-value">Protected value</label>
            <div className="input-with-action input-with-action--no-button">
              <LockKeyhole size={16} aria-hidden="true" />
              <input id="protected-value" value={value} onChange={(event) => setValue(event.target.value)} placeholder="TEST_SECRET_ABC123" autoComplete="off" />
            </div>
          </div>
          <button className="button button--secondary" type="submit" disabled={addingValue}>
            {addingValue ? <span className="spinner spinner--small" /> : <Plus size={16} />}{addingValue ? 'Adding…' : 'Add value'}
          </button>
        </form>
        {protectedValues.length === 0 ? (
          <EmptyState icon={LockKeyhole} title="No protected values" description="Add a fake secret, identifier, or policy phrase to test for unintended disclosure." />
        ) : (
          <ul className="protected-list">
            {protectedValues.map((item) => (
              <li key={item.id}>
                <span className="protected-list__icon" aria-hidden="true"><LockKeyhole size={16} /></span>
                <div><strong>{item.name}</strong><code>{item.display_value}</code></div>
                <span className="protected-list__date">Added {formatDateTime(item.created_at)}</span>
                <button className="icon-button icon-button--danger" type="button" aria-label={`Remove ${item.name}`} onClick={() => setDeleteValue(item)}><Trash2 size={16} /></button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <div className="panel__header"><div><h2>Evaluation history</h2><p>Security runs completed for this target.</p></div></div>
        {evaluations.length === 0 ? (
          <EmptyState icon={Radar} title="No runs for this target" description="Start an evaluation to run Sentinel's adversarial test suite." action={<RunEvaluationButton targetId={id} onError={setRunError} />} />
        ) : <RunTable runs={evaluations} targetsById={targetsById} />}
      </section>

      <section className="danger-zone">
        <div><h2>Delete target</h2><p>Permanently delete this target, its protected values, evaluation history, and test results.</p></div>
        <button className="button button--danger-outline" type="button" onClick={() => setDeleteTargetOpen(true)}><Trash2 size={16} />Delete target</button>
      </section>

      <ConfirmDialog
        open={Boolean(deleteValue)}
        title="Remove protected value?"
        description={`Sentinel will stop checking responses for ${deleteValue?.name || 'this value'}.`}
        confirmLabel="Remove value"
        busy={deleting}
        onCancel={() => setDeleteValue(null)}
        onConfirm={() => void handleDeleteValue()}
      />
      <ConfirmDialog
        open={deleteTargetOpen}
        title="Delete target?"
        description={`This will permanently remove ${target.name} and all its protected values, evaluation history, and test results. This action cannot be undone.`}
        confirmLabel="Delete target"
        busy={deleting}
        onCancel={() => setDeleteTargetOpen(false)}
        onConfirm={() => void handleDeleteTarget()}
      />
    </div>
  )
}

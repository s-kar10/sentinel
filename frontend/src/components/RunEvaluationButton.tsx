import { useRef, useState } from 'react'
import { Play, RotateCw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../lib/api'

interface RunEvaluationButtonProps {
  targetId: number
  compact?: boolean
  onError?: (message: string) => void
}

export function RunEvaluationButton({ targetId, compact = false, onError }: RunEvaluationButtonProps) {
  const key = useRef(crypto.randomUUID())
  const navigate = useNavigate()
  const [versions, setVersions] = useState({ application: '', model: '', prompt: '' })
  const [running, setRunning] = useState(false)

  async function handleRun() {
    setRunning(true)
    onError?.('')
    try {
      const evaluation = await api.startEvaluation(targetId, key.current, Object.fromEntries(Object.entries(versions).filter(([, value]) => value.trim()).map(([name, value]) => [name, value.trim()])))
      navigate(`/evaluations/${evaluation.id}`)
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408) key.current = crypto.randomUUID()
      onError?.(error instanceof Error ? error.message : 'Unable to start the evaluation.')
      setRunning(false)
    }
  }

  return (
    <div>
    {!compact && <details><summary>Optional version labels</summary>{Object.entries(versions).map(([name, value]) => <label key={name}>{name} version <input aria-label={`${name} version`} value={value} maxLength={100} disabled={running} onChange={(event) => { setVersions({ ...versions, [name]: event.target.value }); key.current = crypto.randomUUID() }} /></label>)}</details>}
    <button
      type="button"
      className={`button button--primary ${compact ? 'button--small' : ''}`}
      onClick={handleRun}
      disabled={running}
    >
      {running ? <RotateCw className="spin" size={compact ? 15 : 17} aria-hidden="true" /> : <Play size={compact ? 15 : 17} aria-hidden="true" />}
      {running ? 'Submitting…' : 'Run evaluation'}
    </button>
    </div>
  )
}

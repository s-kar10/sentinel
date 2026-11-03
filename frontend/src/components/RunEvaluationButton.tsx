import { useEffect, useRef, useState } from 'react'
import { Play, RotateCw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { AttackPack } from '../types/api'

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

  const [packs, setPacks] = useState<AttackPack[]>([])
  const [packId, setPackId] = useState('')
  const [packError, setPackError] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    if (compact) return
    let active = true
    api.listAttackPacks().then((items) => {
      if (active) { setPacks(items); setPackError(false) }
    }).catch(() => { if (active) setPackError(true) })
    return () => { active = false }
  }, [compact, loadAttempt])

  async function handleRun() {
    setRunning(true)
    onError?.('')
    try {
      const evaluation = await api.startEvaluation(targetId, key.current, Object.fromEntries(Object.entries(versions).filter(([, value]) => value.trim()).map(([name, value]) => [name, value.trim()])), packs.find((pack) => pack.id === packId))
      navigate(`/evaluations/${evaluation.id}`)
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408) key.current = crypto.randomUUID()
      onError?.(error instanceof Error ? error.message : 'Unable to start the evaluation.')
      setRunning(false)
    }
  }

  return (
    <div>
    {!compact && <>
      <label className="filter-field">Attack pack
        <select aria-label="Attack pack" value={packId} disabled={running} onChange={(event) => { setPackId(event.target.value); key.current = crypto.randomUUID() }}>
          <option value="">Sentinel baseline (8 checks)</option>
          {packs.filter((pack) => pack.id !== 'sentinel-baseline').map((pack) => <option key={pack.id} value={pack.id}>{pack.name} · v{pack.version} · {pack.attacks.length} checks</option>)}
        </select>
      </label>
      {packError && <p role="status">Additional packs unavailable. <button type="button" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Retry pack loading</button></p>}
      {packId && <p>Use an owned security fixture or an authorized adapter for its synthetic protocol. These checks use simulated data and actions.</p>}
    </>}
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

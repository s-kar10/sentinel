import { CheckCircle2, CircleDashed, CircleX, LoaderCircle } from 'lucide-react'
import type { EvaluationStatus, TestOutcome } from '../types/api'

const statusConfig = {
  completed: { icon: CheckCircle2, label: 'Completed' },
  cancelled: { icon: CircleX, label: 'Cancelled' },
  failed: { icon: CircleX, label: 'Failed' },
  running: { icon: LoaderCircle, label: 'Running' },
  pending: { icon: CircleDashed, label: 'Pending' },
} satisfies Record<EvaluationStatus, { icon: typeof CheckCircle2; label: string }>

export function StatusBadge({ status }: { status: EvaluationStatus }) {
  const config = statusConfig[status] || statusConfig.pending
  const Icon = config.icon
  return (
    <span className={`status-badge status-badge--${status}`}>
      <Icon size={13} aria-hidden="true" />
      {config.label}
    </span>
  )
}

export function ResultBadge({ passed, executionError = false, outcome }: { passed: boolean; executionError?: boolean; outcome?: TestOutcome }) {
  const labels = { passed: 'Pass', failed: 'Fail', errored: 'Execution error', untested: 'Untested', not_applicable: 'Not applicable' }
  return (
    <span className={`result-badge ${passed ? 'result-badge--pass' : 'result-badge--fail'}`}>
      {passed ? <CheckCircle2 size={14} aria-hidden="true" /> : <CircleX size={14} aria-hidden="true" />}
      {outcome ? labels[outcome] : executionError ? 'Execution error' : passed ? 'Pass' : 'Fail'}
    </span>
  )
}

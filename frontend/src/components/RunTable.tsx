import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDateTime, formatScore, runTargetName, scoreTone } from '../lib/format'
import type { EvaluationRun } from '../types/api'
import { StatusBadge } from './StatusBadge'

interface RunTableProps {
  runs: EvaluationRun[]
  targetsById?: Map<number, string>
}

export function RunTable({ runs, targetsById }: RunTableProps) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Target</th>
            <th scope="col">Status</th>
            <th scope="col">Score</th>
            <th scope="col">Tests</th>
            <th scope="col">Started</th>
            <th scope="col"><span className="sr-only">Open report</span></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>
                <Link className="table-primary-link" to={`/evaluations/${run.id}`}>
                  {runTargetName(run, targetsById)}
                </Link>
                <span className="table-secondary">Evaluation #{run.id}</span>
              </td>
              <td><StatusBadge status={run.status} /></td>
              <td>
                <strong className={`score-text score-text--${scoreTone(run.score)}`}>
                  {formatScore(run.status === 'completed' && run.total_tests > 0 && (!run.metrics || run.metrics.evaluated > 0) ? run.score : null)}
                </strong>
              </td>
              <td>
                <span className="table-test-count">
                  <span className="is-pass">{run.passed_tests}</span>
                  <span aria-hidden="true"> / </span>
                  <span>{run.total_tests}</span>
                </span>
              </td>
              <td className="table-muted">{formatDateTime(run.started_at)}</td>
              <td>
                <Link className="icon-button" to={`/evaluations/${run.id}`} aria-label={`View evaluation ${run.id}`}>
                  <ArrowRight size={17} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

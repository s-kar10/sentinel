import { JudgeEvidence } from '../components/JudgeEvidence'
import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ExternalLink,
  Filter,
  Radar,
  RotateCw,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { HistoricalAnalysis } from '../components/HistoricalAnalysis'
import { EmptyState, ErrorState, PageLoader } from '../components/AsyncState'
import { PageHeader } from '../components/PageHeader'
import { ResultBadge, StatusBadge } from '../components/StatusBadge'
import { ScoreGauge } from '../components/ScoreGauge'
import { useEvaluationReport } from '../hooks/useEvaluationReport'
import { api } from '../lib/api'
import { formatDateTime, formatDuration, humanizeCategory, runTargetName } from '../lib/format'
import type { CategorySummary, TestResult } from '../types/api'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

type ResultFilter = 'all' | 'failed' | 'passed'

const categoryOrder = [
  'prompt_injection',
  'system_prompt_leakage',
  'sensitive_information_leakage',
  'sensitive_data_leakage',
  'instruction_following',
  'reliability',
]

function calculateBreakdown(results: TestResult[]): Record<string, CategorySummary> {
  return results.reduce<Record<string, CategorySummary>>((summary, result) => {
    const current = summary[result.category] || { total_tests: 0, passed_tests: 0, failed_tests: 0, score: 0 }
    current.total_tests += 1
    current.passed_tests += result.passed ? 1 : 0
    current.failed_tests += result.passed ? 0 : 1
    current.score = (current.passed_tests / current.total_tests) * 100
    summary[result.category] = current
    return summary
  }, {})
}

function severityClass(severity: string): string {
  const normalized = severity.toLowerCase()
  return ['low', 'medium', 'high', 'critical'].includes(normalized) ? normalized : 'medium'
}

export function EvaluationReportPage() {
  const { evaluationId } = useParams()
  const id = Number(evaluationId)
  const { run, results, loading, refreshing, error, retry } = useEvaluationReport(id)
  const [cancelError, setCancelError] = useState('')
  const [resultFilter, setResultFilter] = useState<ResultFilter>('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [outcomeFilter, setOutcomeFilter] = useState('all')

  useDocumentTitle(run ? `Report #${run.id}` : 'Evaluation report')

  const breakdown = useMemo(() => {
    const source = run?.category_breakdown && Object.keys(run.category_breakdown).length > 0
      ? run.category_breakdown
      : calculateBreakdown(results)
    return Object.entries(source).sort(([first], [second]) => {
      const firstIndex = categoryOrder.indexOf(first)
      const secondIndex = categoryOrder.indexOf(second)
      return (firstIndex < 0 ? 99 : firstIndex) - (secondIndex < 0 ? 99 : secondIndex)
    })
  }, [results, run?.category_breakdown])

  const categories = useMemo(() => [...new Set(results.map((result) => result.category))], [results])
  const filteredResults = useMemo(
    () => results.filter((result) => {
      if (resultFilter === 'failed' && result.passed) return false
      if (resultFilter === 'passed' && !result.passed) return false
      if (outcomeFilter !== 'all' && result.outcome !== outcomeFilter) return false
      return categoryFilter === 'all' || result.category === categoryFilter
    }),
    [categoryFilter, resultFilter, outcomeFilter, results],
  )

  if (loading) return <div className="page"><PageLoader label="Building security report" /></div>
  if (!run) {
    return <div className="page"><ErrorState title="Report unavailable" message={error || 'This evaluation could not be found.'} onRetry={retry} /></div>
  }

  const targetName = runTargetName(run)
  const executionErrors = results.filter((result) => result.outcome === 'errored').length
  const behavioralFailures = results.filter((result) => result.outcome === 'failed').length
  const inProgress = run.status === 'pending' || run.status === 'running'

  return (
    <div className="page report-page">
      <Link className="back-link" to="/evaluations"><ArrowLeft size={16} />All evaluations</Link>
      <PageHeader
        eyebrow={`Evaluation #${run.id}`}
        title="Sentinel Security Report"
        description={`${targetName} · Started ${formatDateTime(run.started_at)}`}
        actions={
          <>
            <StatusBadge status={run.status} />
            <Link className="button button--secondary" to={`/targets/${run.target_application_id}`}>
              View target <ExternalLink size={15} />
            </Link>
          </>
        }
      />

      {error && <div className="inline-alert inline-alert--error" role="alert">Report refresh failed. Showing the last saved report; automatic retry continues. <button type="button" onClick={retry}>Retry now</button></div>}

      {cancelError && <div role="alert">{cancelError}</div>}
      {inProgress && <div className="panel" aria-live="polite">
        <p>{run.progress?.completed ?? 0} / {run.progress?.planned ?? run.total_tests} checks completed · {run.progress?.errored ?? 0} execution errors</p>
        <progress aria-label="Evaluation progress" value={run.progress?.completed ?? 0} max={run.total_tests || 1} />
        <button className="button button--secondary" onClick={() => void api.cancelEvaluation(run.id).then(retry).catch((e: Error) => setCancelError(e.message))}>Cancel evaluation</button>
      </div>}
      {run.status === 'cancelled' && <p role="status">Evaluation cancelled. Saved evidence is retained; unstarted checks remain untested.</p>}
      {inProgress ? (
        <section className="running-card" aria-live="polite">
          <span className="running-card__radar" aria-hidden="true"><Radar size={30} /></span>
          <div><p className="eyebrow">Evaluation in progress</p><h2>Sentinel is probing {targetName}</h2><p>Adversarial requests are sent sequentially. This report refreshes automatically.</p></div>
          <span className="running-card__refresh"><RotateCw className={refreshing ? 'spin' : ''} size={16} />{refreshing ? 'Refreshing' : 'Waiting'}</span>
        </section>
      ) : (
        <>
          <section className={`report-hero report-hero--${run.status}`}>
            <div className="report-hero__score"><ScoreGauge score={run.total_tests > 0 && run.status === 'completed' && (!run.metrics || run.metrics.evaluated > 0) ? run.score : null} size="large" /></div>
            <div className="report-hero__summary">
              <p className="eyebrow">Overall posture</p>
              <h2>{run.status === 'cancelled' ? 'Evaluation cancelled' : run.status === 'failed' ? 'Evaluation did not complete' : run.total_tests === 0 ? 'No checks evaluated' : executionErrors > 0 ? 'Some checks could not be evaluated' : 'Evaluation completed'}</h2>
              <p>{run.status === 'failed' ? 'The run stopped early. Any saved results are partial.' : run.total_tests === 0 ? 'There is no evidence to assess this target.' : `${behavioralFailures} checks detected undesirable behavior; ${executionErrors} checks had execution errors.`}</p>
              {run.total_tests > 0 && <p>The original pass rate counts every non-passing check, including errors, untested and inapplicable checks. It is not a security certification.</p>}
            </div>
            <dl className="report-stats">
              <div><dt><CheckCircle2 size={16} />Passed</dt><dd>{run.passed_tests}</dd></div>
              <div><dt><XCircle size={16} />Not passed</dt><dd>{run.failed_tests}</dd></div>
              <div><dt><ShieldAlert size={16} />Total tests</dt><dd>{run.total_tests}</dd></div>
              <div><dt><Clock3 size={16} />Completed</dt><dd>{formatDateTime(run.completed_at)}</dd></div>
            </dl>
          </section>

          <HistoricalAnalysis key={run.id} run={run} />

          {run.metrics && <section className="panel" aria-label="Evaluation coverage and provenance">
            <div className="panel__header"><div><h2>Evaluation coverage and provenance</h2>
              <p>Severity-weighted pass rate: {run.metrics.weighted_score === null ? 'Not scored' : `${run.metrics.weighted_score}%`}. Coverage: {run.metrics.coverage === null ? 'Not applicable' : `${run.metrics.coverage}%`}.</p>
              <p>The weighted rate uses only passed and failed checks. Errors and untested checks reduce coverage; inapplicable checks are excluded. Low/medium/high/critical weights are 1/2/3/4.</p>
              <p>{run.metrics.errored} errored · {run.metrics.untested} untested · {run.metrics.not_applicable} not applicable</p>
              <p>Engine {run.engine_version} · Scoring {run.scoring_version} · Pack {String(run.pack_snapshot?.id ?? 'Unknown')} version {String(run.pack_snapshot?.version ?? '?')}</p>
              <details><summary>Saved definition and fingerprint</summary><pre>{run.pack_digest}</pre><pre>{JSON.stringify(run.pack_snapshot, null, 2)}</pre></details>
            </div></div>
          </section>}

          {breakdown.length > 0 && (
            <section className="panel category-panel">
              <div className="panel__header"><div><h2>Category breakdown</h2><p>Pass rate across each tested security control.</p></div></div>
              <div className="category-grid">
                {breakdown.map(([category, summary]) => (
                  <article className="category-card" key={category}>
                    <div className="category-card__top"><h3>{humanizeCategory(category)}</h3><strong>{Math.round(summary.score)}%</strong></div>
                    <div className="progress-track" role="progressbar" aria-label={`${humanizeCategory(category)} score`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(summary.score)}>
                      <span style={{ width: `${Math.max(0, Math.min(100, summary.score))}%` }} />
                    </div>
                    <p><span>{summary.passed_tests} passed</span><span>{summary.failed_tests} not passed</span></p>
                    {run.metrics?.categories[category] && <p>Coverage: {run.metrics.categories[category].coverage ?? 'N/A'}{run.metrics.categories[category].coverage === null ? '' : '%'} · Weighted: {run.metrics.categories[category].weighted_score ?? 'N/A'}{run.metrics.categories[category].weighted_score === null ? '' : '%'}</p>}
                  </article>
                ))}
              </div>
            </section>
          )}

          <section className="panel findings-panel">
            <div className="panel__header">
              <div><h2>Test results</h2><p>Inspect the attack, captured response, and deterministic verdict for every check.</p></div>
              <span className="count-badge">{filteredResults.length} of {results.length}</span>
            </div>

            {results.length > 0 && (
              <div className="toolbar toolbar--findings">
                <div className="segmented-control" aria-label="Filter results">
                  {(['all', 'failed', 'passed'] as ResultFilter[]).map((filter) => (
                    <button key={filter} type="button" className={resultFilter === filter ? 'is-active' : ''} onClick={() => setResultFilter(filter)}>
                      {filter === 'all' ? 'All results' : filter === 'failed' ? `Not passed (${run.failed_tests})` : `Passed (${run.passed_tests})`}
                    </button>
                  ))}
                </div>
                <label className="filter-field"><Filter size={16} /><span className="sr-only">Filter by category</span><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="all">All categories</option>{categories.map((category) => <option key={category} value={category}>{humanizeCategory(category)}</option>)}</select></label>
                <label className="filter-field"><span className="sr-only">Filter by outcome</span><select value={outcomeFilter} onChange={(event) => setOutcomeFilter(event.target.value)}><option value="all">All outcomes</option>{['passed', 'failed', 'errored', 'untested', 'not_applicable'].map((outcome) => <option key={outcome} value={outcome}>{outcome.replace('_', ' ')}</option>)}</select></label>
              </div>
            )}

            {results.length === 0 ? (
              <EmptyState icon={AlertTriangle} title="No test results recorded" description={run.status === 'failed' ? 'The evaluation stopped before individual results were saved.' : 'This run completed without returning result records.'} />
            ) : filteredResults.length === 0 ? (
              <EmptyState icon={Filter} title="No matching results" description="Change the result or category filter to see more findings." />
            ) : (
              <div className="finding-list">
                {filteredResults.map((result) => (
                  <details className={`finding finding--${result.passed ? 'pass' : 'fail'}`} key={result.id} open={!result.passed}>
                    <summary>
                      <span className="finding__indicator" aria-hidden="true">{result.passed ? <CheckCircle2 size={19} /> : <XCircle size={19} />}</span>
                      <span className="finding__title"><strong>{result.test_name}</strong><span>{humanizeCategory(result.category)}</span></span>
                      <span className={`severity-badge severity-badge--${severityClass(result.severity)}`}>{result.severity}</span>
                      <ResultBadge passed={result.passed} outcome={result.outcome} />
                      <span className="finding__duration">{formatDuration(result.duration_ms)}</span>
                      <ChevronDown className="finding__chevron" size={18} aria-hidden="true" />
                    </summary>
                    <div className="finding__body">
                      {result.attempt_count !== null && <p>Attempts: {result.attempt_count}</p>}
                      <div className="evidence-grid">
                        <div className="evidence-block"><span>Attack prompt</span><pre>{result.prompt}</pre></div>
                        <div className="evidence-block"><span>Target response</span><pre>{result.response ?? 'No response captured.'}</pre></div>
                      </div>
                      <div className={`verdict-note verdict-note--${result.passed ? 'pass' : 'fail'}`}>
                        {result.passed ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
                        <div><strong>{result.passed ? 'Expected behavior observed' : result.outcome === 'errored' ? 'Execution error — behavior was not evaluated' : result.outcome === 'untested' ? 'This check was not executed' : result.outcome === 'not_applicable' ? 'This check did not apply' : 'Detected undesirable behavior'}</strong><p>{result.failure_reason || (result.passed ? 'The applicable assertions passed.' : 'Inspect the assertion outcomes below.')}</p></div>
                      </div>
                      <JudgeEvidence assertions={result.assertion_results} />
                      {result.assertion_results && <div className="evidence-block"><span>Assertion outcomes and evidence</span><pre>{JSON.stringify(result.assertion_results, null, 2)}</pre></div>}
                      {result.provenance && <details><summary>Attack definition</summary><pre>{JSON.stringify(result.provenance, null, 2)}</pre></details>}
                      {result.observation_snapshot && <details><summary>Structured response</summary><pre>{JSON.stringify(result.observation_snapshot, null, 2)}</pre></details>}
                    </div>
                  </details>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

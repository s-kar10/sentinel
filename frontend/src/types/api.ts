export type EntityId = number

export type HttpMethod = 'POST'

export interface TargetApplication {
  id: EntityId
  name: string
  endpoint_url: string
  http_method: string
  request_template: Record<string, unknown>
  prompt_field: string
  response_field: string
  has_api_key: boolean
  created_at: string
  updated_at: string
}

export interface TargetInput {
  name: string
  endpoint_url: string
  http_method: HttpMethod
  api_key?: string | null
  request_template: Record<string, unknown>
  prompt_field: string
  response_field: string
}

export type TargetUpdateInput = Partial<TargetInput>

export interface ProtectedValue {
  id: EntityId
  target_application_id: EntityId
  name: string
  display_value: string
  created_at: string
}

export interface ProtectedValueInput {
  name: string
  value: string
}

export type EvaluationStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type TestSeverity = 'low' | 'medium' | 'high' | 'critical'
export type TestOutcome = 'passed' | 'failed' | 'errored' | 'untested' | 'not_applicable'

export interface OutcomeMetrics {
  passed: number
  failed: number
  errored: number
  untested: number
  not_applicable: number
  evaluated: number
  coverage: number | null
  weighted_score: number | null
}

export interface AssertionResult {
  index: number
  evaluator: string
  version: number
  outcome: TestOutcome
  code: string
  evidence: Record<string, unknown>
}

export interface EvaluationRun {
  id: EntityId
  target_application_id: EntityId
  status: EvaluationStatus
  started_at: string | null
  completed_at: string | null
  total_tests: number
  passed_tests: number
  failed_tests: number
  score: number
  target_name: string
  version_tags: Record<string, string | null> | null
  progress: { planned: number; completed: number; errored: number }
  created_at: string
  category_breakdown: Record<string, CategorySummary>
  engine_version: string | null
  scoring_version: string | null
  pack_digest: string | null
  pack_snapshot: Record<string, unknown> | null
  metrics: (OutcomeMetrics & { categories: Record<string, OutcomeMetrics> }) | null
}

export interface CategorySummary {
  total_tests: number
  passed_tests: number
  failed_tests: number
  score: number
}

export interface TestResult {
  id: EntityId
  evaluation_run_id: EntityId
  test_name: string
  category: string
  severity: TestSeverity | string
  prompt: string
  response: string | null
  passed: boolean
  failure_reason: string | null
  duration_ms: number
  attempt_count: number | null
  outcome: TestOutcome
  response_status: number | null
  provenance: Record<string, unknown> | null
  assertion_results: AssertionResult[] | null
  observation_snapshot: Record<string, unknown> | null
  created_at: string
}

export interface HealthResponse {
  status: 'ok'
  service: 'sentinel-api'
}

export type ApiValidationIssue = {
  loc?: Array<string | number>
  msg?: string
  message?: string
}

export interface Baseline { id: number; target_id: number; run_id: number; name: string; created_at: string }
export interface HistoryPoint {
  run_id: number
  status: EvaluationStatus
  versions: Record<string, string | null> | null
  compatible: boolean
  metrics: (OutcomeMetrics & { categories: Record<string, OutcomeMetrics> }) | null
  security_metrics: OutcomeMetrics | null
  latency: { sample_size: number; mean_ms: number | null; median_ms: number | null }
}
export interface Comparison {
  compatible: boolean
  flags: string[]
  sample_sizes: { paired_behavioral: number }
  regressions: string[]
  improvements: string[]
  execution_errors: string[]
  added_attacks: string[]
  removed_attacks: string[]
  coverage_changes: unknown[]
  effect: { change_percentage_points: number | null }
  latency: { paired_sample_size: number; paired_mean_change_ms: number | null }
}
export interface HistoryAnalytics {
  points: HistoryPoint[]
  through_run_id: number
  truncated: boolean
  repetition: {
    policy: string
    groups: { versions: Record<string, string | null>; status: string; repeated_regressions: string[]; needs_review: string[] }[]
  }
}

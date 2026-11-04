import { accessSnapshot, endAccess } from './access'
import type {
  AttackPack, ApiValidationIssue, Baseline, Comparison, HistoryAnalytics,
  EntityId,
  EvaluationRun,
  HealthResponse,
  ProtectedValue,
  ProtectedValueInput,
  TargetApplication,
  TargetInput,
  TargetUpdateInput,
  TestResult,
} from '../types/api'

const DEFAULT_API_URL = 'http://localhost:8000'
export const API_URL = (import.meta.env.VITE_API_URL || DEFAULT_API_URL).replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly details: unknown

  constructor(message: string, status: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

function validationMessage(issues: ApiValidationIssue[]): string | undefined {
  const messages = issues
    .map((issue) => issue.msg || issue.message)
    .filter((message): message is string => Boolean(message))

  return messages.length > 0 ? messages.join(' · ') : undefined
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback

  const body = payload as Record<string, unknown>
  if (typeof body.message === 'string') return body.message
  if (typeof body.error === 'string') return body.error
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    return validationMessage(body.detail as ApiValidationIssue[]) || fallback
  }
  return fallback
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 45_000): Promise<T> {
  const access = accessSnapshot()
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
  const abort = () => controller.abort()
  init.signal?.addEventListener('abort', abort, { once: true })
  if (init.signal?.aborted) controller.abort()

  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
        ...(access.token ? { Authorization: `Bearer ${access.token}` } : {}),
      },
      signal: controller.signal,
    })

    const contentType = response.headers.get('content-type') || ''
    const payload: unknown = contentType.includes('application/json')
      ? await response.json()
      : await response.text()

    if (access.generation !== accessSnapshot().generation) {
      throw new ApiError('Access changed while the request was in progress.', 401)
    }
    if (!response.ok) {
      if (response.status === 401 && access.token) endAccess(access.generation)
      throw new ApiError(
        errorMessage(payload, `Request failed with status ${response.status}`),
        response.status,
        payload,
      )
    }

    if (response.status === 204) return undefined as T
    return payload as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('The request took too long. Check the service and try again.', 408)
    }
    throw new ApiError('Unable to reach the Sentinel API. Confirm that the backend is running.', 0, error)
  } finally {
    window.clearTimeout(timeoutId)
    init.signal?.removeEventListener('abort', abort)
  }
}

function unwrapList<T>(payload: T[] | { items?: T[]; data?: T[]; results?: T[] }): T[] {
  if (Array.isArray(payload)) return payload
  return payload.items || payload.data || payload.results || []
}

function unwrapEntity<T>(payload: T | { data: T }): T {
  if (payload && typeof payload === 'object' && 'data' in payload) return payload.data
  return payload
}

export const api = {
  accessStatus: () => request<{ mode: 'local' | 'token' }>('/auth/status'),
  accessIdentity: () => request<{ name: string; role: string; token_id: number | null }>('/auth/me'),
  health: () => request<HealthResponse>('/health'),

  listTargets: async () => {
    const payload = await request<TargetApplication[] | { items?: TargetApplication[]; data?: TargetApplication[] }>(
      '/targets',
    )
    return unwrapList(payload)
  },

  getTarget: async (id: EntityId) =>
    unwrapEntity(await request<TargetApplication | { data: TargetApplication }>(`/targets/${id}`)),

  createTarget: async (input: TargetInput) =>
    unwrapEntity(
      await request<TargetApplication | { data: TargetApplication }>('/targets', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    ),

  updateTarget: async (id: EntityId, input: TargetUpdateInput) =>
    unwrapEntity(
      await request<TargetApplication | { data: TargetApplication }>(`/targets/${id}`, {
        method: 'PUT',
        body: JSON.stringify(input),
      }),
    ),

  deleteTarget: (id: EntityId) => request<void>(`/targets/${id}`, { method: 'DELETE' }),

  listProtectedValues: async (targetId: EntityId) => {
    const payload = await request<
      ProtectedValue[] | { items?: ProtectedValue[]; data?: ProtectedValue[] }
    >(`/targets/${targetId}/protected-values`)
    return unwrapList(payload)
  },

  createProtectedValue: async (targetId: EntityId, input: ProtectedValueInput) =>
    unwrapEntity(
      await request<ProtectedValue | { data: ProtectedValue }>(`/targets/${targetId}/protected-values`, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    ),

  deleteProtectedValue: (id: EntityId) =>
    request<void>(`/protected-values/${id}`, { method: 'DELETE' }),

  listAttackPacks: () => request<AttackPack[]>('/attack-packs'),

  startEvaluation: async (targetId: EntityId, key: string, versions: Record<string, string>, attackPack?: AttackPack) =>
    unwrapEntity(
      await request<EvaluationRun | { data: EvaluationRun }>(`/targets/${targetId}/evaluation-jobs`, {
        method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ versions, ...(attackPack ? { attack_pack: attackPack } : {}) }),
      }),
    ),

  listBaselines: (targetId: number) => request<Baseline[]>(`/targets/${targetId}/baselines`),
  createBaseline: (targetId: number, runId: number, name: string) => request<Baseline>(`/targets/${targetId}/baselines`, { method: 'POST', body: JSON.stringify({ run_id: runId, name }) }),
  compareEvaluation: (id: number, baselineId: number, signal?: AbortSignal) => request<Comparison>(`/evaluations/${id}/comparison?baseline_id=${baselineId}`, { signal }),
  getAnalytics: (targetId: number, baselineId: number, signal?: AbortSignal) => request<HistoryAnalytics>(`/targets/${targetId}/analytics?baseline_id=${baselineId}`, { signal }),

  cancelEvaluation: (id: EntityId) => request<EvaluationRun>(`/evaluations/${id}/cancel`, { method: 'POST' }),

  listEvaluations: async () => {
    const payload = await request<EvaluationRun[] | { items?: EvaluationRun[]; data?: EvaluationRun[] }>(
      '/evaluations',
    )
    return unwrapList(payload)
  },

  getEvaluation: async (id: EntityId, signal?: AbortSignal) =>
    unwrapEntity(await request<EvaluationRun | { data: EvaluationRun }>(`/evaluations/${id}`, { signal })),

  getEvaluationResults: async (id: EntityId, signal?: AbortSignal) => {
    const payload = await request<TestResult[] | { items?: TestResult[]; data?: TestResult[]; results?: TestResult[] }>(
      `/evaluations/${id}/results`, { signal },
    )
    return unwrapList(payload)
  },
}

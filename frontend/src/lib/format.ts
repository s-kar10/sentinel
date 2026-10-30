import type { EvaluationRun } from '../types/api'

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return 'Not started'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown time'

  const seconds = Math.round((date.getTime() - Date.now()) / 1000)
  const ranges: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 60 * 60 * 24 * 365],
    ['month', 60 * 60 * 24 * 30],
    ['week', 60 * 60 * 24 * 7],
    ['day', 60 * 60 * 24],
    ['hour', 60 * 60],
    ['minute', 60],
  ]
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

  for (const [unit, divisor] of ranges) {
    if (Math.abs(seconds) >= divisor) return formatter.format(Math.round(seconds / divisor), unit)
  }
  return 'just now'
}

export function formatScore(score: number | null | undefined): string {
  return score == null || !Number.isFinite(score) ? '—' : `${Math.round(score)}%`
}

export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds == null || !Number.isFinite(milliseconds)) return '—'
  if (milliseconds < 1_000) return `${Math.round(milliseconds)} ms`
  return `${(milliseconds / 1_000).toFixed(2)} s`
}

export function runTargetName(run: EvaluationRun, targetsById?: Map<number, string>): string {
  return (
    run.target_name ||
    targetsById?.get(run.target_application_id) ||
    `Target #${run.target_application_id}`
  )
}

export function scoreTone(score: number | null | undefined): 'good' | 'warning' | 'danger' | 'muted' {
  if (score == null) return 'muted'
  if (score >= 80) return 'good'
  if (score >= 60) return 'warning'
  return 'danger'
}

export function humanizeCategory(category: string): string {
  return category
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

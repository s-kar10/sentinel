import type { LucideIcon } from 'lucide-react'
import { AlertCircle, Inbox, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

export function PageLoader({ label = 'Loading Sentinel' }: { label?: string }) {
  return (
    <div className="page-loader" role="status" aria-label={label}>
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

interface ErrorStateProps {
  title?: string
  message: string
  onRetry?: () => void
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }: ErrorStateProps) {
  return (
    <div className="state-card state-card--error" role="alert">
      <span className="state-card__icon" aria-hidden="true">
        <AlertCircle size={23} />
      </span>
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
        {onRetry && (
          <button type="button" className="button button--secondary button--small" onClick={onRetry}>
            <RefreshCw size={15} aria-hidden="true" />
            Try again
          </button>
        )}
      </div>
    </div>
  )
}

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  description: string
  action?: ReactNode
}

export function EmptyState({ icon: Icon = Inbox, title, description, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-state__icon" aria-hidden="true">
        <Icon size={24} />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  )
}

export function TableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="skeleton-table" aria-label="Loading" role="status">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index}>
          <span className="skeleton skeleton--wide" />
          <span className="skeleton skeleton--medium" />
          <span className="skeleton skeleton--short" />
        </div>
      ))}
    </div>
  )
}

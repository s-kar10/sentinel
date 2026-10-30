import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Never include target payloads or protected values in production telemetry.
    console.error('Sentinel UI error', error.name, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children

    return (
      <main className="fatal-error">
        <div className="fatal-error__card">
          <span className="fatal-error__icon" aria-hidden="true">
            <AlertTriangle size={24} />
          </span>
          <p className="eyebrow">Unexpected error</p>
          <h1>Sentinel hit a problem</h1>
          <p>The interface could not finish rendering. Reload to start from a clean state.</p>
          <button className="button button--primary" onClick={() => window.location.reload()}>
            Reload Sentinel
          </button>
        </div>
      </main>
    )
  }
}

import { ArrowLeft, SearchX } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function NotFoundPage() {
  useDocumentTitle('Page not found')
  return (
    <div className="page not-found">
      <span className="not-found__icon" aria-hidden="true"><SearchX size={30} /></span>
      <p className="eyebrow">404 · Not found</p>
      <h1>This page is outside the perimeter</h1>
      <p>The Sentinel page you requested does not exist or may have moved.</p>
      <Link className="button button--primary" to="/"><ArrowLeft size={16} />Return to overview</Link>
    </div>
  )
}

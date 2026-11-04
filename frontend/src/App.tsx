import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AccessGate } from './components/AccessGate'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { AppShell } from './components/AppShell'
import { ScrollToTop } from './components/ScrollToTop'
import { DashboardPage } from './pages/DashboardPage'
import { EvaluationReportPage } from './pages/EvaluationReportPage'
import { EvaluationsPage } from './pages/EvaluationsPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { TargetDetailPage } from './pages/TargetDetailPage'
import { TargetFormPage } from './pages/TargetFormPage'
import { TargetsPage } from './pages/TargetsPage'

export default function App() {
  return (
    <AppErrorBoundary>
      <AccessGate><BrowserRouter>
        <ScrollToTop />
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="targets" element={<TargetsPage />} />
            <Route path="targets/new" element={<TargetFormPage />} />
            <Route path="targets/:targetId" element={<TargetDetailPage />} />
            <Route path="targets/:targetId/edit" element={<TargetFormPage />} />
            <Route path="evaluations" element={<EvaluationsPage />} />
            <Route path="evaluations/:evaluationId" element={<EvaluationReportPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </BrowserRouter></AccessGate>
    </AppErrorBoundary>
  )
}

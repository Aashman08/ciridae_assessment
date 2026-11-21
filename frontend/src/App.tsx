import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { Shell } from './components/Shell'
import { Empty, Loaded } from './components/ui'
import { api } from './lib/api'
import { Ask } from './pages/Ask'
import { Connectors } from './pages/Connectors'
import { Issues } from './pages/Issues'
import { Activity } from './pages/Activity'
import { IssueTypes } from './pages/IssueTypes'
import { JobDetail } from './pages/JobDetail'
import { Jobs } from './pages/Jobs'
import { Lines } from './pages/Lines'
import { Overview } from './pages/Overview'

/**
 * Issues no longer have a page of their own. An old link to one, such as a
 * source under an answer from the assistant, goes to the job it is on.
 */
function IssueRedirect() {
  const { issueId = '' } = useParams()
  const issue = useQuery({ queryKey: ['issue', Number(issueId)], queryFn: () => api.issue(Number(issueId)) })
  return (
    <Loaded query={issue}>
      {(data) => <Navigate replace to={data.job_number ? `/jobs/${data.job_number}` : '/issues?open=no-job'} />}
    </Loaded>
  )
}

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="ask" element={<Ask />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="jobs/:jobNumber" element={<JobDetail />} />
        <Route path="issues" element={<Issues />} />
        <Route path="issues/:issueId" element={<IssueRedirect />} />
        <Route path="invoices" element={<Lines key="invoices" kind="customer_invoice" />} />
        <Route path="bills" element={<Lines key="bills" kind="vendor_bill" />} />
        <Route path="audit-log" element={<Activity />} />
        {/* The page was called Activity at first; old links still land on it. */}
        <Route path="activity" element={<Navigate to="/audit-log" replace />} />
        <Route path="checks" element={<IssueTypes />} />
        <Route path="issue-types" element={<Navigate to="/checks" replace />} />
        <Route path="connectors" element={<Connectors />} />
        <Route path="*" element={<Empty>There is no page at this address</Empty>} />
      </Route>
    </Routes>
  )
}

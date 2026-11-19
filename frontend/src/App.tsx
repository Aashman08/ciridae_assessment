import { Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import { Empty } from './components/ui'
import { IssueDetail } from './pages/IssueDetail'
import { Issues } from './pages/Issues'
import { IssueTypes } from './pages/IssueTypes'
import { JobDetail } from './pages/JobDetail'
import { Jobs } from './pages/Jobs'
import { Lines } from './pages/Lines'
import { Overview } from './pages/Overview'

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="jobs/:jobNumber" element={<JobDetail />} />
        <Route path="issues" element={<Issues />} />
        <Route path="issues/:issueId" element={<IssueDetail />} />
        <Route path="invoices" element={<Lines key="invoices" kind="customer_invoice" />} />
        <Route path="bills" element={<Lines key="bills" kind="vendor_bill" />} />
        <Route path="issue-types" element={<IssueTypes />} />
        <Route path="*" element={<Empty>There is no page at this address</Empty>} />
      </Route>
    </Routes>
  )
}

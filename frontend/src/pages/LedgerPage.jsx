import LedgerViewer from '../components/LedgerViewer.jsx'

/** The audit chain, on a page of its own rather than sharing one with the graph. */
export default function LedgerPage({ refreshKey }) {
  return (
    <div className="h-full overflow-hidden">
      <LedgerViewer refreshKey={refreshKey} />
    </div>
  )
}

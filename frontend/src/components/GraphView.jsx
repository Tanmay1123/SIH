import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'

/**
 * The network explorer.
 *
 * Nodes are companies coloured by risk score, edges are trade relationships
 * (one edge per company pair, not one per invoice). Selecting a ring in the
 * alerts feed highlights its members and the loop between them, which is the
 * moment the whole idea becomes visible: a closed circle in a graph that
 * otherwise only ever flows one way.
 */

const riskColour = (score, inRing) => {
  if (score >= 70) return '#dc2626' // high risk
  if (score >= 40) return '#ea580c' // elevated
  if (score > 0) return '#0891b2' // scored, low
  return inRing ? '#475569' : '#334155' // unscored
}

const stylesheet = [
  {
    selector: 'node',
    style: {
      'background-color': (n) => riskColour(n.data('risk_score'), n.data('in_ring')),
      label: 'data(label)',
      color: '#94a3b8',
      'font-size': '7px',
      'text-valign': 'bottom',
      'text-margin-y': 3,
      'text-max-width': '70px',
      'text-wrap': 'ellipsis',
      width: (n) => 10 + Math.min(n.data('risk_score'), 100) / 6,
      height: (n) => 10 + Math.min(n.data('risk_score'), 100) / 6,
      'border-width': 1,
      'border-color': '#0f172a',
    },
  },
  {
    selector: 'edge',
    style: {
      width: 0.8,
      'line-color': '#334155',
      'target-arrow-color': '#334155',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.5,
      'curve-style': 'bezier',
      opacity: 0.55,
    },
  },
  // The selected ring: its members and the loop connecting them.
  {
    selector: 'node.ring-member',
    style: {
      'border-width': 3,
      'border-color': '#fbbf24',
      color: '#fde68a',
      'font-size': '9px',
      'z-index': 10,
    },
  },
  {
    selector: 'edge.ring-edge',
    style: {
      width: 3,
      'line-color': '#fbbf24',
      'target-arrow-color': '#fbbf24',
      'arrow-scale': 1.1,
      opacity: 1,
      'z-index': 10,
    },
  },
  { selector: '.dimmed', style: { opacity: 0.12 } },
  {
    selector: 'node:selected',
    style: { 'border-width': 3, 'border-color': '#f8fafc' },
  },
]

export default function GraphView({
  graph,
  selectedRing,
  onSelectCompany,
  loading,
  ringMembersOnly,
  onToggleScope,
}) {
  const containerRef = useRef(null)
  const cyRef = useRef(null)
  const onSelectCompanyRef = useRef(onSelectCompany)
  onSelectCompanyRef.current = onSelectCompany

  // Build / rebuild the graph when the data changes.
  useEffect(() => {
    if (!containerRef.current || !graph) return

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...graph.nodes, ...graph.edges],
      style: stylesheet,
      layout: {
        // cose gives an organic layout that makes closed loops visually
        // obvious; the node count here is small enough for it to settle fast.
        name: 'cose',
        animate: false,
        nodeRepulsion: 9000,
        idealEdgeLength: 60,
        nodeOverlap: 12,
        gravity: 0.3,
        numIter: 900,
      },
      wheelSensitivity: 0.25,
      minZoom: 0.15,
      maxZoom: 4,
    })

    cy.on('tap', 'node', (evt) => {
      onSelectCompanyRef.current?.(Number(evt.target.id()))
    })

    cyRef.current = cy
    return () => {
      cy.destroy()
      cyRef.current = null
    }
  }, [graph])

  // Highlight whichever ring is currently selected.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    let members = cy.collection()

    cy.batch(() => {
      cy.elements().removeClass('ring-member ring-edge dimmed')

      if (!selectedRing?.company_ids?.length) return

      const ids = selectedRing.company_ids.map(String)
      ids.forEach((id) => {
        const node = cy.getElementById(id)
        if (node.nonempty()) members.merge(node)
      })
      if (members.empty()) return

      // Highlight the hops that actually close the loop: A->B->C->A.
      const loopEdges = cy.collection()
      ids.forEach((source, i) => {
        const target = ids[(i + 1) % ids.length]
        loopEdges.merge(cy.edges(`[source = "${source}"][target = "${target}"]`))
      })

      cy.elements().addClass('dimmed')
      members.removeClass('dimmed').addClass('ring-member')
      loopEdges.removeClass('dimmed').addClass('ring-edge')
    })

    // Outside the batch: batched style updates and animation do not mix.
    if (members.nonempty()) {
      cy.animate({ fit: { eles: members, padding: 90 }, duration: 350 })
    }
  }, [selectedRing, graph])

  return (
    <div className="relative h-full w-full">
      <div className="absolute left-3 top-3 z-10 flex items-center gap-2">
        <button
          onClick={onToggleScope}
          className="rounded border border-slate-700 bg-slate-900/90 px-2.5 py-1 text-xs text-slate-300 hover:border-slate-500 hover:text-white"
        >
          {ringMembersOnly ? 'Show full network' : 'Show ring members only'}
        </button>
        {graph && (
          <span className="rounded bg-slate-900/90 px-2 py-1 text-xs text-slate-500">
            {graph.nodes.length} companies · {graph.edges.length} trade links
          </span>
        )}
      </div>

      <div className="absolute right-3 top-3 z-10 rounded border border-slate-800 bg-slate-900/90 px-3 py-2 text-xs">
        <div className="mb-1 font-medium text-slate-400">Risk</div>
        {[
          ['#dc2626', 'High (70+)'],
          ['#ea580c', 'Elevated (40-70)'],
          ['#0891b2', 'Low'],
          ['#334155', 'Not in a loop'],
        ].map(([colour, label]) => (
          <div key={label} className="flex items-center gap-2 text-slate-400">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: colour }}
            />
            {label}
          </div>
        ))}
      </div>

      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-950/60 text-sm text-slate-400">
          Building graph…
        </div>
      )}

      {!loading && graph && graph.nodes.length === 0 && (
        <div className="absolute inset-0 z-20 flex items-center justify-center px-8 text-center text-sm text-slate-500">
          No companies to display. Seed the database, then run detection.
        </div>
      )}

      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}

import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'

/**
 * The network explorer, built to match how Obsidian's graph view actually
 * works (not just how it looks):
 *
 * - Labels are invisible when zoomed out and fade in only as you zoom into a
 *   region ("text fade threshold" in Obsidian's own settings). This is the
 *   part that matters most: with 250 nodes, showing every label at once is
 *   unreadable no matter how small the dots are. Zoom in on a cluster to
 *   read it; zoomed out, you see shape only.
 * - Node size scales with how many trading partners a company has (Obsidian:
 *   "the more nodes that reference a given node, the bigger it gets"), with
 *   a modest extra bump for confirmed high risk.
 * - Plain thin straight lines, no arrowheads - direction is shown in the
 *   evidence panel's numbered loop list instead, where it's legible.
 * - A calm staggered reveal (positions precomputed and hidden, then faded in
 *   in small connectivity-ordered batches) instead of a physics simulation
 *   visibly flinging nodes around.
 */

// Warm green (safe) through amber to red (high risk) - no blue/cyan anywhere.
const riskColour = (score, inRing) => {
  if (score >= 70) return '#dc2626' // high risk - red
  if (score >= 40) return '#d97706' // elevated - amber
  if (score > 0) return '#4d7c0f' // scored, low - warm green
  return inRing ? '#71717a' : '#52525b' // unscored - neutral gray
}

const BASE_NODE_SIZE = 5
const MAX_DEGREE_BONUS = 7
const HIGH_RISK_MULTIPLIER = 1.25

// Obsidian scales a node by how many other notes link to it. Here that's how
// many distinct companies a company has traded with - a hub in the network
// reads as a bigger dot, exactly like a heavily-linked note does.
function nodeSize(node) {
  const degree = node.degree(false)
  const bySize = BASE_NODE_SIZE + Math.min(Math.log2(degree + 1) * 2, MAX_DEGREE_BONUS)
  const risk = node.data('risk_score')
  return risk >= 70 ? bySize * HIGH_RISK_MULTIPLIER : bySize
}

// Cytoscape renders to a <canvas>, which Tailwind's dark: classes can't
// reach - so the stylesheet itself has to know the theme. Only the values
// that actually clash across themes differ; risk/highlight colours read
// fine on both a near-black and a near-white background.
function buildStylesheet(dark) {
  const edgeLine = dark ? '#3f3f46' : '#a1a1aa'
  const nodeBorder = dark ? '#0a0a0a' : '#fafafa'
  const labelColour = dark ? '#a1a1aa' : '#52525b'
  const selectedBorder = dark ? '#fafafa' : '#18181b'

  return [
    {
      selector: 'node',
      style: {
        'background-color': (n) => riskColour(n.data('risk_score'), n.data('in_ring')),
        label: 'data(label)',
        color: labelColour,
        'font-size': '7px',
        'text-valign': 'bottom',
        'text-margin-y': 3,
        'text-max-width': '70px',
        'text-wrap': 'ellipsis',
        // Label opacity is driven separately, per zoom level - see
        // updateLabelFade(). This stylesheet default only matters before
        // that first runs.
        'text-opacity': 0,
        width: nodeSize,
        height: nodeSize,
        'border-width': 1,
        'border-color': nodeBorder,
        opacity: 1,
      },
    },
    {
      // Plain thin lines, no arrowheads - Obsidian's graph doesn't show
      // direction either.
      selector: 'edge',
      style: {
        width: 0.5,
        'line-color': edgeLine,
        'curve-style': 'straight',
        opacity: 0.35,
      },
    },
    // The selected ring: its members and the loop connecting them. Always
    // fully labelled regardless of zoom - this is the one thing you came
    // here to read.
    {
      selector: 'node.ring-member',
      style: {
        'border-width': 2.5,
        'border-color': '#fbbf24',
        color: '#d97706',
        'font-size': '10px',
        'text-opacity': 1,
        'z-index': 10,
      },
    },
    {
      selector: 'edge.ring-edge',
      style: {
        width: 2,
        'line-color': '#fbbf24',
        opacity: 1,
        'z-index': 10,
      },
    },
    { selector: '.dimmed', style: { opacity: 0.08 } },
    {
      selector: 'node:selected',
      style: { 'border-width': 2.5, 'border-color': selectedBorder },
    },
  ]
}

export default function GraphView({
  graph,
  selectedRing,
  onSelectCompany,
  loading,
  ringMembersOnly,
  onToggleScope,
  theme,
}) {
  const containerRef = useRef(null)
  const cyRef = useRef(null)
  const onSelectCompanyRef = useRef(onSelectCompany)
  onSelectCompanyRef.current = onSelectCompany
  // Cytoscape's inline .style() calls (what the zoom handler uses) always
  // beat stylesheet class rules, regardless of when the class was added - so
  // "ring-member" forcing text-opacity:1 in the stylesheet isn't enough by
  // itself if that node already got an inline text-opacity from an earlier
  // zoom while it wasn't selected yet. The ring-highlight effect needs to
  // call this to resync inline text-opacity from the current zoom whenever
  // the selection changes, in both directions.
  const updateLabelFadeRef = useRef(null)

  // Build / rebuild the graph when the data changes.
  useEffect(() => {
    if (!containerRef.current || !graph) return

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: buildStylesheet(theme === 'dark'),
      wheelSensitivity: 0.25,
      minZoom: 0.15,
      maxZoom: 6,
    })

    cy.on('tap', 'node', (evt) => {
      onSelectCompanyRef.current?.(Number(evt.target.id()))
    })

    // Obsidian's graph view doesn't fling everything around while it settles
    // - positions are already decided, and nodes simply fade/grow into place,
    // rippling outward from wherever the graph is "entered". We get that by
    // computing the whole layout instantly while every element sits at
    // opacity 0 (so the physics settling is never visible), then revealing
    // nodes in small staggered batches, connectivity order, ordinary edges
    // fading in only once both of their endpoints are already visible.
    const eles = cy.add([...graph.nodes, ...graph.edges])
    eles.style({ opacity: 0 })
    cy.nodes().style({ width: 1, height: 1 })

    // Spacing scales with graph size so a 250-node full network gets more
    // room to spread out than a 20-node ring-members-only view, rather than
    // both using the same fixed distance.
    const n = graph.nodes.length || 1
    cy.layout({
      name: 'cose',
      animate: false,
      randomize: true,
      nodeRepulsion: 6000 * n,
      idealEdgeLength: 45 + Math.sqrt(n) * 3,
      nodeOverlap: 14,
      gravity: 0.25,
      numIter: 1500,
    }).run()

    // Zoomed out: shape only, no labels - reading 250 overlapping names at
    // once is what made this unreadable before. Zoom into a region and its
    // labels fade in. Thresholds are relative to the zoom level right after
    // fitting the whole graph, so this behaves the same whether the view has
    // 20 nodes or 250.
    const fitZoom = cy.zoom()
    const FADE_START = fitZoom * 1.6
    const FADE_DONE = fitZoom * 3.2
    const updateLabelFade = () => {
      const z = cy.zoom()
      const t = Math.max(0, Math.min(1, (z - FADE_START) / (FADE_DONE - FADE_START)))
      // Ring-member nodes force their own text-opacity to 1 via the
      // stylesheet's higher-specificity class rule - leave them out of this
      // bulk (inline-style) update so that override isn't clobbered.
      cy.nodes().not('.ring-member').style('text-opacity', t)
    }
    cy.on('zoom', updateLabelFade)
    updateLabelFade()
    updateLabelFadeRef.current = updateLabelFade
    if (import.meta.env.DEV) window.__cy = cy // dev-only inspection hook

    // Node reveal order: a BFS per connected component, so a cluster of
    // trading partners ripples outward together rather than the whole graph
    // popping in in id order.
    const nodeOrder = []
    const seen = new Set()
    cy.nodes().forEach((root) => {
      if (seen.has(root.id())) return
      const { path } = cy.elements().bfs({ roots: root, directed: false })
      path.forEach((ele) => {
        if (ele.isNode() && !seen.has(ele.id())) {
          seen.add(ele.id())
          nodeOrder.push(ele)
        }
      })
    })

    let cancelled = false
    let timer = null
    const revealedNodes = new Set()
    const edges = cy.edges()

    // Slow and deliberate, not a race: a 250-node network should still take
    // several unhurried seconds to fully materialise, the way Obsidian's does
    // on a large vault rather than snapping in.
    const STEPS = 70
    const STEP_MS = 70
    const batchSize = Math.max(1, Math.ceil(nodeOrder.length / STEPS))
    let cursor = 0

    const revealBatch = () => {
      if (cancelled) return
      const batch = nodeOrder.slice(cursor, cursor + batchSize)
      cursor += batchSize

      batch.forEach((node) => {
        revealedNodes.add(node.id())
        node.animate(
          { style: { opacity: 1, width: nodeSize(node), height: nodeSize(node) } },
          { duration: 450, easing: 'ease-out-cubic' },
        )
      })

      edges.forEach((edge) => {
        if (edge.hasClass('revealed')) return
        if (revealedNodes.has(edge.data('source')) && revealedNodes.has(edge.data('target'))) {
          edge.addClass('revealed')
          edge.animate({ style: { opacity: 0.35 } }, { duration: 450, easing: 'ease-out-cubic' })
        }
      })

      if (cursor < nodeOrder.length) {
        timer = setTimeout(revealBatch, STEP_MS)
      }
    }
    revealBatch()

    cyRef.current = cy
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
      cy.removeListener('zoom', updateLabelFade)
      // Nothing here has a pending requestAnimationFrame-driven layout to
      // race with anymore (the layout ran with animate:false, synchronously)
      // - only per-element .animate() calls, which cytoscape itself cancels
      // cleanly on destroy.
      cy.destroy()
      cyRef.current = null
    }
  }, [graph])

  // Swap the stylesheet in place when the theme changes - cheap, and never
  // touches positions or re-triggers the reveal.
  useEffect(() => {
    cyRef.current?.style(buildStylesheet(theme === 'dark'))
  }, [theme])

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

      // Force it inline too: an earlier zoom-out may have already stamped
      // text-opacity:0 directly on these nodes, which would otherwise still
      // beat the stylesheet's .ring-member rule.
      members.style('text-opacity', 1)
    })

    // Selection cleared: let every node's label go back to being governed by
    // the current zoom level instead of staying forced-visible.
    if (!selectedRing?.company_ids?.length) {
      updateLabelFadeRef.current?.()
    }

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
          className="rounded border border-zinc-300 bg-white/90 px-2.5 py-1 text-xs text-zinc-700 hover:border-zinc-400 hover:text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900/90 dark:text-zinc-300 dark:hover:border-zinc-500 dark:hover:text-white"
        >
          {ringMembersOnly ? 'Show full network' : 'Show ring members only'}
        </button>
        {graph && (
          <span className="rounded bg-white/90 px-2 py-1 text-xs text-zinc-500 dark:bg-zinc-900/90">
            {graph.nodes.length} companies · {graph.edges.length} trade links · scroll to zoom in for names
          </span>
        )}
      </div>

      <div className="absolute right-3 top-3 z-10 rounded border border-zinc-200 bg-white/90 px-3 py-2 text-xs dark:border-zinc-800 dark:bg-zinc-900/90">
        <div className="mb-1 font-medium text-zinc-600 dark:text-zinc-400">Risk</div>
        {[
          ['#dc2626', 'High (70+)'],
          ['#d97706', 'Elevated (40-70)'],
          ['#4d7c0f', 'Low'],
          ['#52525b', 'Not in a loop'],
        ].map(([colour, label]) => (
          <div key={label} className="flex items-center gap-2 text-zinc-600 dark:text-zinc-400">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: colour }}
            />
            {label}
          </div>
        ))}
      </div>

      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/60 text-sm text-zinc-500 dark:bg-zinc-950/60 dark:text-zinc-400">
          Building graph…
        </div>
      )}

      {!loading && graph && graph.nodes.length === 0 && (
        <div className="absolute inset-0 z-20 flex items-center justify-center px-8 text-center text-sm text-zinc-500">
          No companies to display. Upload a dataset, then run detection.
        </div>
      )}

      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}

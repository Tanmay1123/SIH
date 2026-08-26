import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { getToken } from '../api'
import {
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  Mono,
  Spinner,
  cx,
  formatInr,
} from '../components/ui.jsx'
import {
  CheckIcon,
  DatabaseIcon,
  HubIcon,
  LoopIcon,
  MoonIcon,
  NetworkIcon,
  SunIcon,
  UploadIcon,
} from '../icons.jsx'
import { downloadDataset, getLabPresets, loadIntoConsole, previewDataset } from './labApi'

/**
 * The Dataset Lab.
 *
 * A workshop that sits beside the console rather than inside it. It has no nav
 * rail, no dataset picker, no officer, no case: it takes a seed and a mix, and
 * turns them into two CSV files. Keeping it visually separate is the point -
 * every number on this page is invented, and nothing on it should ever be
 * mistaken for a finding about a real business.
 *
 * The one thing that makes it more than a random-data script is the second
 * half of the screen. After generating, the page runs the REAL detection
 * pipeline over the result and shows what came out: how the alerts scored,
 * how much of the planted fraud was actually surfaced, and how many honest
 * businesses got pushed over the high-risk line. The generator does not get to
 * mark its own homework.
 */

const BAND_STYLE = {
  high: {
    bar: 'bg-red-500',
    dot: 'bg-red-500',
    text: 'text-red-600 dark:text-red-400',
    chip: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/60 dark:text-red-300',
  },
  medium: {
    bar: 'bg-amber-500',
    dot: 'bg-amber-500',
    text: 'text-amber-600 dark:text-amber-400',
    chip: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-300',
  },
  low: {
    bar: 'bg-sky-500',
    dot: 'bg-sky-500',
    text: 'text-sky-600 dark:text-sky-400',
    chip: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/60 dark:text-sky-300',
  },
  clean: {
    bar: 'bg-zinc-300 dark:bg-zinc-700',
    dot: 'bg-zinc-400',
    text: 'text-zinc-500',
    chip: 'border-zinc-200 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400',
  },
}

const BAND_ORDER = ['high', 'medium', 'low', 'clean']

/** The knobs, in the order they make sense to turn. */
const CONTROLS = [
  {
    key: 'companies',
    label: 'Companies',
    hint: 'Size of the whole economy, honest businesses included.',
    step: 20,
    min: 60,
    max: 1200,
    band: null,
  },
  {
    key: 'rings',
    label: 'Circular-trade rings',
    hint: 'Shell companies invoicing each other in a closed loop. Every flag showing.',
    step: 1,
    min: 0,
    max: 25,
    band: 'high',
  },
  {
    key: 'mills',
    label: 'Fake invoice mills',
    hint: 'Sells to dozens of buyers, buys from nobody. No loop to find.',
    step: 1,
    min: 0,
    max: 25,
    band: 'high',
  },
  {
    key: 'grey_rings',
    label: 'Ambiguous loops',
    hint: 'Real loops, but only one or two flags each. These need a human.',
    step: 1,
    min: 0,
    max: 25,
    band: 'medium',
  },
  {
    key: 'grey_mills',
    label: 'Borderline sellers',
    hint: 'Lopsided books that only just clear the mill detector. Some will not.',
    step: 1,
    min: 0,
    max: 25,
    band: 'medium',
  },
  {
    key: 'honest_loops',
    label: 'Honest two-way traders',
    hint: 'Genuine businesses that form real loops. Flagging these is a mistake.',
    step: 1,
    min: 0,
    max: 50,
    band: 'low',
  },
]

export default function LabPage({ theme, onToggleTheme }) {
  const [spec, setSpec] = useState(null)
  const [presets, setPresets] = useState([])
  const [activePreset, setActivePreset] = useState('balanced')

  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  const signedIn = Boolean(getToken())

  useEffect(() => {
    getLabPresets()
      .then((data) => {
        setPresets(data.presets)
        const first = data.presets.find((p) => p.key === 'balanced') || data.presets[0]
        setSpec(first ? { ...first.spec } : data.defaults)
      })
      .catch((e) =>
        setError(
          e?.response?.data?.detail ||
            `Cannot reach the API. Is the backend running? (${e.message})`,
        ),
      )
  }, [])

  const set = (key, value) => {
    setSpec((s) => ({ ...s, [key]: value }))
    setActivePreset(null)
  }

  const applyPreset = (preset) => {
    setSpec({ ...preset.spec })
    setActivePreset(preset.key)
    setResult(null)
    setNotice(null)
  }

  const run = useCallback(
    async (action) => {
      if (!spec) return
      setBusy(action)
      setError(null)
      setNotice(null)
      try {
        if (action === 'preview') {
          setResult(await previewDataset(spec))
        } else if (action === 'download') {
          const filename = await downloadDataset(spec)
          setNotice(`Saved ${filename} — companies.csv, invoices.csv, the answer key and a note.`)
        } else if (action === 'load') {
          const loaded = await loadIntoConsole(spec, '')
          setNotice(
            `Loaded "${loaded.dataset_name}" into the console: ${loaded.companies_created} companies, ` +
              `${loaded.invoices_created} invoices. It is now the active dataset — open Detections and run it.`,
          )
        }
      } catch (e) {
        if (e?.response?.status === 401) {
          setError('Loading into the console needs an account. Sign in to the console first, then come back.')
        } else {
          setError(e?.response?.data?.detail || e.message)
        }
      } finally {
        setBusy(null)
      }
    },
    [spec],
  )

  if (!spec) {
    return (
      <div className="flex h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        {error ? (
          <Banner tone="danger" className="max-w-md">{error}</Banner>
        ) : (
          <Spinner />
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <LabHeader theme={theme} onToggleTheme={onToggleTheme} />

      {/* One column, three bands: choose, then build, then read the result.
          It used to be a narrow controls column beside a wide results column,
          which meant the controls ran three screens deep while the results
          panel sat empty next to them. Nothing here needs to be tall - the
          knobs are seven numbers - so they go across instead of down, and the
          results get the full width they actually want for their tables. */}
      <div className="mx-auto max-w-[88rem] space-y-5 px-6 py-6">
        {error && <Banner tone="danger">{error}</Banner>}
        {notice && (
          <Banner tone="good">
            <CheckIcon className="h-3.5 w-3.5 shrink-0" />
            <span className="flex-1">{notice}</span>
          </Banner>
        )}

        {/* ---------------- 1. presets ---------------- */}
        <Card>
          <CardHeader
            title="Start from a preset"
            subtitle="Then change anything you like below."
          />
          <div className="grid gap-2.5 px-5 pb-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {presets.map((preset) => (
              <button
                key={preset.key}
                onClick={() => applyPreset(preset)}
                className={cx(
                  'rounded-lg border p-3.5 text-left transition-colors',
                  activePreset === preset.key
                    ? 'border-amber-400 bg-amber-50 dark:border-amber-600/70 dark:bg-amber-950/40'
                    : 'border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:border-zinc-700 dark:hover:bg-zinc-900',
                )}
              >
                <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {preset.label}
                </div>
                <div className="mt-1 text-[11px] leading-relaxed text-zinc-500">
                  {preset.blurb}
                </div>
              </button>
            ))}
          </div>
        </Card>

        {/* ---------------- 2. the mix ---------------- */}
        <Card>
          <CardHeader
            title="The mix"
            subtitle="What gets planted, and how much of it. The same seed always rebuilds the same dataset, exactly."
          />
          <div className="grid gap-x-5 gap-y-4 px-5 pb-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <SeedControl value={spec.seed} onChange={(v) => set('seed', v)} />
            {CONTROLS.map((control) => (
              <Counter
                key={control.key}
                control={control}
                value={spec[control.key]}
                onChange={(v) => set(control.key, v)}
              />
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-zinc-200 px-5 py-4 dark:border-zinc-800">
            <p className="min-w-[16rem] flex-1 text-[11px] leading-relaxed text-zinc-500">
              {signedIn ? (
                <>
                  <strong className="font-medium text-zinc-700 dark:text-zinc-300">
                    Generate &amp; test
                  </strong>{' '}
                  builds the dataset and runs the console&rsquo;s real detector over it without
                  saving anything. Only <em>Load</em> writes to the database.
                </>
              ) : (
                <>
                  Generating and downloading need no account. Loading data into the console does —{' '}
                  <Link
                    to="/"
                    className="font-medium text-amber-700 hover:underline dark:text-amber-400"
                  >
                    sign in
                  </Link>{' '}
                  and come back.
                </>
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                onClick={() => run('preview')}
                disabled={Boolean(busy)}
                className="!bg-amber-600 hover:!bg-amber-500"
              >
                {busy === 'preview' ? (
                  <Spinner className="h-3.5 w-3.5" />
                ) : (
                  <NetworkIcon className="h-4 w-4" />
                )}
                {busy === 'preview' ? 'Generating…' : 'Generate & test'}
              </Button>
              <Button onClick={() => run('download')} disabled={Boolean(busy)}>
                {busy === 'download' ? (
                  <Spinner className="h-3.5 w-3.5" />
                ) : (
                  <DatabaseIcon className="h-4 w-4" />
                )}
                Download
              </Button>
              <Button
                onClick={() => run('load')}
                disabled={Boolean(busy) || !signedIn}
                title={
                  signedIn
                    ? 'Create this as a dataset in the console'
                    : 'Sign in to the console first'
                }
              >
                {busy === 'load' ? (
                  <Spinner className="h-3.5 w-3.5" />
                ) : (
                  <UploadIcon className="h-4 w-4" />
                )}
                Load into console
              </Button>
            </div>
          </div>
        </Card>

        {/* ---------------- 3. results ---------------- */}
        {!result && <Placeholder busy={busy === 'preview'} />}
        {result && <Results result={result} />}

        {/* ---------------- reference ---------------- */}
        <Explainer />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function LabHeader({ theme, onToggleTheme }) {
  return (
    <header className="relative overflow-hidden border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      {/* Graph paper. A workshop bench, not a case file - the console never
          looks like this, which is the whole idea. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.55] dark:opacity-[0.25]"
        style={{
          backgroundImage:
            'linear-gradient(currentColor 1px, transparent 1px), linear-gradient(90deg, currentColor 1px, transparent 1px)',
          backgroundSize: '22px 22px',
          color: 'rgb(203 213 225 / 0.5)',
          maskImage: 'linear-gradient(to bottom, black, transparent)',
          WebkitMaskImage: 'linear-gradient(to bottom, black, transparent)',
        }}
      />
      <div className="relative mx-auto flex max-w-[88rem] flex-wrap items-center gap-4 px-6 py-5">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-600 ring-1 ring-amber-500/30 dark:text-amber-400">
          <FlaskIcon className="h-6 w-6" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Dataset Lab
            </h1>
            <Badge tone="warn">Fabricated data</Badge>
          </div>
          <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-zinc-500">
            Builds GST trade networks to test the console with. Every company, GSTIN, director,
            address and rupee on this page was invented by a random number generator — none of it
            is, or came from, a real taxpayer.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onToggleTheme}
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
          >
            {theme === 'dark' ? <SunIcon className="h-4 w-4" /> : <MoonIcon className="h-4 w-4" />}
          </button>
          <Link
            to="/"
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-300 px-3.5 text-sm font-medium text-zinc-700 transition-colors hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-600 dark:hover:bg-zinc-800"
          >
            Fraud console
            <span aria-hidden>→</span>
          </Link>
        </div>
      </div>
    </header>
  )
}

function FlaskIcon({ className }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M10 3h4" />
      <path d="M10 3v6.5L4.6 18a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3L14 9.5V3" />
      <path d="M6.8 14.5h10.4" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

function SeedControl({ value, onChange }) {
  return (
    <ControlCell
      label="Seed"
      hint="The number every random choice is drawn from. Keep it to reproduce a dataset; roll it for a fresh one."
      control={
        <>
          <Input
            type="number"
            value={value}
            onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
            className="h-7 w-[4.75rem] py-0 text-center font-mono text-xs"
          />
          <button
            onClick={() => onChange(Math.floor(Math.random() * 100000))}
            title="Roll a new seed"
            className="flex h-7 w-7 items-center justify-center rounded-md border border-zinc-300 text-zinc-500 transition-colors hover:border-zinc-400 hover:text-zinc-800 dark:border-zinc-700 dark:hover:border-zinc-600 dark:hover:text-zinc-200"
          >
            <DiceIcon className="h-3.5 w-3.5" />
          </button>
        </>
      }
    />
  )
}

function DiceIcon({ className }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" className={className}>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <circle cx="8.5" cy="8.5" r="1.1" fill="currentColor" />
      <circle cx="15.5" cy="15.5" r="1.1" fill="currentColor" />
      <circle cx="15.5" cy="8.5" r="1.1" fill="currentColor" />
      <circle cx="8.5" cy="15.5" r="1.1" fill="currentColor" />
    </svg>
  )
}

/**
 * One knob.
 *
 * Label and stepper share the top line; the sentence explaining what the knob
 * does gets the cell's full width underneath it. Putting the hint beside a
 * narrow label column is what made these wrap into five-line slivers.
 */
function ControlCell({ dot, label, hint, control }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        {dot && <span className={cx('h-2 w-2 shrink-0 rounded-full', dot)} />}
        {/* Wraps rather than truncating: at laptop widths "Honest two-way
            traders" would otherwise end in an ellipsis, and a knob whose name
            you cannot read is not a knob. */}
        <span className="min-w-0 flex-1 text-sm font-medium leading-snug text-zinc-800 dark:text-zinc-200">
          {label}
        </span>
        <span className="flex shrink-0 items-center gap-1">{control}</span>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{hint}</p>
    </div>
  )
}

function Counter({ control, value, onChange }) {
  const clamp = (v) => Math.max(control.min, Math.min(control.max, v))
  const style = control.band ? BAND_STYLE[control.band] : null

  return (
    <ControlCell
      dot={style?.dot}
      label={control.label}
      hint={control.hint}
      control={
        <>
          <StepButton
            onClick={() => onChange(clamp(value - control.step))}
            disabled={value <= control.min}
            aria-label={`Fewer ${control.label}`}
          >
            −
          </StepButton>
          <input
            type="number"
            value={value}
            aria-label={control.label}
            onChange={(e) => onChange(clamp(Number(e.target.value) || 0))}
            className="h-7 w-14 rounded-md border border-zinc-300 bg-white text-center font-mono text-xs text-zinc-900 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/15 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
          />
          <StepButton
            onClick={() => onChange(clamp(value + control.step))}
            disabled={value >= control.max}
            aria-label={`More ${control.label}`}
          >
            +
          </StepButton>
        </>
      }
    />
  )
}

function StepButton({ children, ...rest }) {
  return (
    <button
      {...rest}
      className="flex h-7 w-7 items-center justify-center rounded-md border border-zinc-300 text-sm text-zinc-600 transition-colors hover:border-zinc-400 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-zinc-600 dark:hover:bg-zinc-800"
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// The explainer - what a ring is, what a mill is
// ---------------------------------------------------------------------------

function Explainer() {
  return (
    <Card>
      <CardHeader
        title="The two shapes"
        subtitle="Both are fraud. Only one of them is a loop — which is why the console has two detectors and counts them separately."
      />
      <div className="grid gap-4 px-5 pb-5 md:grid-cols-2">
        <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <LoopIcon className="h-4 w-4 shrink-0 text-red-500" />
            <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              Circular-trade ring
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <div className="w-40 shrink-0">
              <Diagram kind="ring" />
            </div>
            <p className="min-w-[14rem] flex-1 text-[11px] leading-relaxed text-zinc-500">
              A group of shell companies bill each other in a closed circle: A sells to B, B to C,
              C back to A. Nothing is ever produced or delivered — the same money goes round and
              round, and each hop generates a tax credit to claim. Because it closes, the graph
              contains a <em>cycle</em>, and that is what cycle detection looks for.
            </p>
          </div>
        </div>

        <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <div className="flex flex-wrap items-center gap-2">
            <HubIcon className="h-4 w-4 shrink-0 text-amber-500" />
            <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              Fake invoice mill
            </span>
            <Badge tone="warn">this is what “mill” means</Badge>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <div className="w-40 shrink-0">
              <Diagram kind="mill" />
            </div>
            <div className="min-w-[14rem] flex-1 space-y-2">
              <p className="text-[11px] leading-relaxed text-zinc-500">
                A mill exists only to <strong>churn out invoices</strong> — like a mill churning
                out flour, except the product is paperwork. It sells to dozens of unrelated
                businesses that want a tax credit to claim, and buys from almost nobody, because
                nothing it “sold” ever existed. Then it stops filing and vanishes.
              </p>
              <p className="text-[11px] leading-relaxed text-zinc-500">
                That shape is a <strong>star, not a loop</strong>. There is no cycle in it, so
                cycle detection can run forever and never see one.
              </p>
            </div>
          </div>
        </div>
      </div>
    </Card>
  )
}

/** Small inline diagrams. Cheap to draw, and they explain the shape instantly. */
function Diagram({ kind }) {
  if (kind === 'ring') {
    return (
      <svg viewBox="0 0 200 76" className="mt-3 w-full" role="img" aria-label="Three companies invoicing each other in a circle">
        <defs>
          <marker id="lab-arrow-red" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0 0 L8 4 L0 8 z" fill="currentColor" />
          </marker>
        </defs>
        <g className="text-red-500" stroke="currentColor" strokeWidth="1.4" fill="none" markerEnd="url(#lab-arrow-red)">
          <path d="M62 24 L128 24" />
          <path d="M140 34 L112 58" />
          <path d="M88 60 L60 36" />
        </g>
        <g className="fill-zinc-100 stroke-zinc-300 dark:fill-zinc-800 dark:stroke-zinc-600" strokeWidth="1">
          <circle cx="52" cy="24" r="14" />
          <circle cx="148" cy="24" r="14" />
          <circle cx="100" cy="64" r="14" />
        </g>
        <g className="fill-zinc-600 dark:fill-zinc-300" fontSize="11" textAnchor="middle" fontWeight="600">
          <text x="52" y="28">A</text>
          <text x="148" y="28">B</text>
          <text x="100" y="68">C</text>
        </g>
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 200 76" className="mt-3 w-full" role="img" aria-label="One company invoicing many unrelated buyers">
      <defs>
        <marker id="lab-arrow-amber" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto">
          <path d="M0 0 L8 4 L0 8 z" fill="currentColor" />
        </marker>
      </defs>
      <g className="text-amber-500" stroke="currentColor" strokeWidth="1.4" fill="none" markerEnd="url(#lab-arrow-amber)">
        {[8, 26, 44, 62, 80].map((y, i) => (
          <path key={i} d={`M56 38 L${132} ${y + 2}`} />
        ))}
      </g>
      <circle cx="42" cy="38" r="15" className="fill-amber-100 stroke-amber-400 dark:fill-amber-950 dark:stroke-amber-600" strokeWidth="1.2" />
      <g className="fill-zinc-100 stroke-zinc-300 dark:fill-zinc-800 dark:stroke-zinc-600" strokeWidth="1">
        {[10, 28, 46, 64, 82].map((y, i) => (
          <circle key={i} cx="146" cy={y - 4} r="8" />
        ))}
      </g>
      <text x="42" y="42" fontSize="10" textAnchor="middle" fontWeight="700" className="fill-amber-700 dark:fill-amber-300">
        MILL
      </text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

function Placeholder({ busy }) {
  return (
    <Card className="flex min-h-[15rem] flex-col items-center justify-center gap-3 px-6 py-10 text-center">
      {busy ? (
        <>
          <Spinner className="h-6 w-6" />
          <p className="text-sm text-zinc-500">
            Building the network, then running the real detector over it…
          </p>
        </>
      ) : (
        <>
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400">
            <NetworkIcon className="h-6 w-6" />
          </span>
          <div className="max-w-lg">
            <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              Nothing generated yet
            </p>
            <p className="mt-1 text-xs leading-relaxed text-zinc-500">
              Press <strong>Generate &amp; test</strong> above. The lab will build the dataset and
              then run the console&rsquo;s actual detection pipeline over it, so you can see what
              the officer&rsquo;s queue would look like before you upload anything. New to the two
              kinds of fraud? They are explained at the bottom of this page.
            </p>
          </div>
        </>
      )}
    </Card>
  )
}

function Results({ result }) {
  const { summary, analysis, sample } = result
  const bands = summary.bands
  const total = BAND_ORDER.reduce((sum, b) => sum + (bands[b] || 0), 0) || 1

  return (
    <>
      {/* What was planted and what was found sit side by side deliberately:
          the comparison between them is the entire point of the page, and
          stacking them put a scroll between the two halves of one thought. */}
      <div className="grid gap-5 lg:grid-cols-2">
      {/* ---- what was built ---- */}
      <Card>
        <CardHeader
          title="What was built"
          subtitle={`${summary.companies} companies and ${summary.invoices.toLocaleString('en-IN')} invoices, ${summary.first_invoice} to ${summary.last_invoice}.`}
        />
        <div className="grid grid-cols-2 gap-4 px-5 pb-4 xl:grid-cols-4">
          <Figure label="Companies" value={summary.companies.toLocaleString('en-IN')} />
          <Figure label="Invoices" value={summary.invoices.toLocaleString('en-IN')} />
          <Figure label="Value invoiced" value={formatInr(summary.total_value)} />
          <Figure
            label="No e-way bill"
            value={`${Math.round((summary.missing_eway / Math.max(summary.invoices, 1)) * 100)}%`}
            hint={`${summary.missing_eway.toLocaleString('en-IN')} invoices`}
          />
        </div>

        <div className="px-5 pb-5">
          <div className="mb-2 flex h-2.5 overflow-hidden rounded-full">
            {BAND_ORDER.map((band) =>
              bands[band] ? (
                <div
                  key={band}
                  className={BAND_STYLE[band].bar}
                  style={{ width: `${(bands[band] / total) * 100}%` }}
                  title={`${bands[band]} ${summary.band_labels[band]}`}
                />
              ) : null,
            )}
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
            {BAND_ORDER.map((band) => (
              <div key={band} className="flex items-start gap-2">
                <span className={cx('mt-1 h-2 w-2 shrink-0 rounded-full', BAND_STYLE[band].dot)} />
                <div className="min-w-0">
                  <span className="text-xs font-medium text-zinc-800 dark:text-zinc-200">
                    {bands[band]} {summary.band_labels[band].toLowerCase()}
                  </span>
                  <p className="text-[11px] leading-relaxed text-zinc-500">
                    {summary.band_blurbs[band]}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Card>

      {/* ---- what the detector found ---- */}
      <Scorecard analysis={analysis} />
      </div>

      {/* ---- the alerts themselves ---- */}
      <AlertTable analysis={analysis} />

      {/* ---- the files ---- */}
      <SampleFiles sample={sample} />
    </>
  )
}

function Figure({ label, value, hint }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-medium uppercase tracking-[0.09em] text-zinc-500">
        {label}
      </div>
      <div className="mt-1 truncate text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
        {value}
      </div>
      {hint && <div className="truncate text-[11px] text-zinc-500">{hint}</div>}
    </div>
  )
}

function Scorecard({ analysis }) {
  const { score_bands: scoreBands, scorecard, threshold } = analysis
  const totalAlerts = scorecard.alerts_total || 1
  const missed = scorecard.high_planted - scorecard.high_found

  return (
    <Card>
      <CardHeader
        title="What the detector actually found"
        subtitle={`The real pipeline, run over this data. High risk means ${threshold} or above — the threshold set in the console.`}
      />

      <div className="px-5 pb-5">
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          {['high', 'medium', 'low'].map((band) => (
            <div
              key={band}
              className={cx('rounded-lg border px-3.5 py-3', BAND_STYLE[band].chip)}
            >
              <div className="text-2xl font-semibold tracking-tight">
                {scoreBands[band] ?? 0}
              </div>
              <div className="text-[11px] font-medium">
                {band === 'high'
                  ? `alerts at ${threshold}+`
                  : band === 'medium'
                    ? 'alerts in the grey zone'
                    : 'alerts scored low'}
              </div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-current/15">
                <div
                  className={cx('h-full rounded-full', BAND_STYLE[band].bar)}
                  style={{ width: `${((scoreBands[band] ?? 0) / totalAlerts) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        <dl className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
          <Line
            label="Planted fraud surfaced"
            value={`${scorecard.high_found} of ${scorecard.high_planted}`}
            tone={missed === 0 ? 'good' : 'warn'}
            note={
              missed === 0
                ? 'Every ring and mill built into this dataset produced an alert.'
                : `${missed} planted ${missed === 1 ? 'group' : 'groups'} produced no alert at all.`
            }
          />
          <Line
            label="Grey-zone cases surfaced"
            value={`${scorecard.medium_found} of ${scorecard.medium_planted}`}
            tone="neutral"
            note="Ambiguous by design. Some are meant to slip past — that is what the threshold costs."
          />
          <Line
            label="Honest businesses over the line"
            value={String(scorecard.false_alarms)}
            tone={scorecard.false_alarms === 0 ? 'good' : 'danger'}
            note={
              scorecard.false_alarms === 0
                ? 'No genuine two-way trader was scored high risk.'
                : 'Genuine traders scored high risk. Every one is an officer’s wasted day.'
            }
          />
          <Line
            label="Alerts in total"
            value={String(scorecard.alerts_total)}
            tone="neutral"
            note="One loop can be reported several times — the same companies, entered at different points."
          />
        </dl>
      </div>
    </Card>
  )
}

function Line({ label, value, note, tone }) {
  const toneClass =
    tone === 'good'
      ? 'text-brand-600 dark:text-brand-300'
      : tone === 'warn'
        ? 'text-amber-600 dark:text-amber-400'
        : tone === 'danger'
          ? 'text-red-600 dark:text-red-400'
          : 'text-zinc-900 dark:text-zinc-100'

  return (
    <div className="border-t border-zinc-200 pt-2.5 dark:border-zinc-800">
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-xs text-zinc-600 dark:text-zinc-400">{label}</dt>
        <dd className={cx('shrink-0 font-mono text-sm font-semibold', toneClass)}>{value}</dd>
      </div>
      <p className="mt-0.5 text-[11px] leading-relaxed text-zinc-500">{note}</p>
    </div>
  )
}

function AlertTable({ analysis }) {
  const [showAll, setShowAll] = useState(false)
  const alerts = useMemo(
    () => (showAll ? analysis.alerts : analysis.alerts.slice(0, 12)),
    [analysis.alerts, showAll],
  )

  if (!analysis.alerts.length) {
    return (
      <Card className="px-5 py-10 text-center">
        <p className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
          The detector found nothing in this dataset.
        </p>
        <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-zinc-500">
          That is a real result, not an error — with no rings, mills or two-way traders planted,
          the generated economy is a plain supply chain and contains no loops at all.
        </p>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader
        title="The queue this would produce"
        subtitle="What an officer would open the console to. Sorted the way they would see it."
        actions={
          analysis.alerts.length > 12 && (
            <Button size="sm" variant="ghost" onClick={() => setShowAll((v) => !v)}>
              {showAll ? 'Show fewer' : `Show all ${analysis.alerts.length}`}
            </Button>
          )
        }
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[42rem] text-left">
          <thead>
            <tr className="border-b border-zinc-200 text-[10px] uppercase tracking-[0.08em] text-zinc-500 dark:border-zinc-800">
              <th className="px-5 py-2 font-medium">Risk</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Companies</th>
              <th className="px-3 py-2 font-medium">Value</th>
              <th className="px-5 py-2 font-medium">Was it really fraud?</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/70">
            {alerts.map((alert, i) => (
              <tr key={i} className="align-top">
                <td className="px-5 py-2.5">
                  <span className={cx('font-mono text-sm font-semibold', BAND_STYLE[alert.score_band].text)}>
                    {alert.risk_score.toFixed(1)}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className="inline-flex items-center gap-1.5 text-xs text-zinc-700 dark:text-zinc-300">
                    {alert.kind === 'mill' ? (
                      <HubIcon className="h-3.5 w-3.5 text-amber-500" />
                    ) : (
                      <LoopIcon className="h-3.5 w-3.5 text-red-500" />
                    )}
                    {alert.kind === 'mill' ? 'Mill' : 'Ring'}
                    {alert.closure === 'control' && (
                      <span className="text-[10px] text-zinc-400" title="The loop closes through a shared director or address, not through an invoice">
                        · ownership
                      </span>
                    )}
                  </span>
                </td>
                <td className="max-w-[16rem] px-3 py-2.5 text-xs text-zinc-600 dark:text-zinc-400">
                  <span className="line-clamp-2">
                    {alert.members.join(', ')}
                    {alert.size > alert.members.length && ` +${alert.size - alert.members.length}`}
                  </span>
                </td>
                <td className="px-3 py-2.5 font-mono text-xs text-zinc-600 dark:text-zinc-400">
                  {formatInr(alert.value)}
                </td>
                <td className="px-5 py-2.5">
                  <Verdict alert={alert} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-zinc-200 px-5 py-3 text-[11px] leading-relaxed text-zinc-500 dark:border-zinc-800">
        The last column compares each alert against the answer key — what that company was
        actually built as. The detector never sees it.
      </p>
    </Card>
  )
}

function Verdict({ alert }) {
  const map = {
    high: { tone: 'danger', label: 'Planted fraud' },
    medium: { tone: 'warn', label: 'Planted grey zone' },
    low: { tone: 'info', label: 'Honest trader' },
    clean: { tone: 'neutral', label: 'Ordinary business' },
  }
  const { tone, label } = map[alert.planted_band]
  const wrong =
    alert.score_band === 'high' && (alert.planted_band === 'low' || alert.planted_band === 'clean')

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge tone={tone}>{label}</Badge>
      {wrong && <span className="text-[10px] font-medium text-red-600 dark:text-red-400">false alarm</span>}
      {alert.planted_groups.length > 0 && (
        <Mono className="text-[10px]">{alert.planted_groups.join(' ')}</Mono>
      )}
    </div>
  )
}

function SampleFiles({ sample }) {
  const [tab, setTab] = useState('companies')
  const rows = sample[tab] || []
  const columns = rows.length ? Object.keys(rows[0]) : []

  const TABS = [
    { key: 'companies', label: 'companies.csv' },
    { key: 'invoices', label: 'invoices.csv' },
    { key: 'answer_key', label: 'answer_key.csv' },
  ]

  return (
    <Card>
      <CardHeader
        title="The files you get"
        subtitle="First few rows of each. Download gives you all of them, zipped, with a note explaining what is inside."
        actions={
          <div className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cx(
                  'rounded-md px-2.5 py-1 font-mono text-[11px] transition-colors',
                  tab === t.key
                    ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                    : 'text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        }
      />
      {tab === 'answer_key' && (
        <div className="mx-5 mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[11px] leading-relaxed text-amber-800 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300">
          This one is <strong>not</strong> an upload file. It records what each company was
          planted as, so you can check the results afterwards. Keep it out of the console.
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[44rem] text-left font-mono text-[11px]">
          <thead>
            <tr className="border-b border-zinc-200 text-zinc-500 dark:border-zinc-800">
              {columns.map((c) => (
                <th key={c} className="whitespace-nowrap px-3 py-2 font-medium first:pl-5 last:pr-5">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/70">
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td
                    key={c}
                    className="max-w-[13rem] truncate px-3 py-1.5 text-zinc-600 first:pl-5 last:pr-5 dark:text-zinc-400"
                    title={String(row[c])}
                  >
                    {String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

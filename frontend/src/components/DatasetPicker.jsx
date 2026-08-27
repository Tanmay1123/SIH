import { useEffect, useRef, useState } from 'react'
import { activateDataset, deleteDataset, getDatasets, renameDataset } from '../api'
import { ChevronDownIcon, DatabaseIcon, EditIcon, TrashIcon } from '../icons.jsx'

/**
 * Which upload the console is looking at.
 *
 * Uploading no longer wipes anything, so several datasets coexist. This is how
 * an officer moves between them: pick a past upload and its detection runs,
 * alerts and scores all come back with it.
 */

const when = (iso) =>
  iso ? new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : ''

export default function DatasetPicker({ activeId, onChanged }) {
  const [open, setOpen] = useState(false)
  const [datasets, setDatasets] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null)
  const [draftName, setDraftName] = useState('')
  const boxRef = useRef(null)

  const load = () =>
    getDatasets()
      .then(setDatasets)
      .catch((e) => setError(e.message))

  // Loaded on mount, not only when the menu opens - otherwise the button has
  // no name to show and reads "No dataset" while one is plainly active.
  useEffect(() => {
    load()
  }, [activeId])

  useEffect(() => {
    if (open) load()
  }, [open])

  // Close when clicking anywhere else.
  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const active = datasets.find((d) => d.id === activeId)

  const handleActivate = async (id) => {
    setBusy(true)
    setError(null)
    try {
      await activateDataset(id)
      setOpen(false)
      await onChanged()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (dataset) => {
    if (!window.confirm(`Delete "${dataset.name}" and everything detected from it?`)) return
    setBusy(true)
    setError(null)
    try {
      await deleteDataset(dataset.id)
      await load()
      await onChanged()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleRename = async (id) => {
    const name = draftName.trim()
    setEditing(null)
    if (!name) return
    try {
      await renameDataset(id, name)
      await load()
      await onChanged()
    } catch (e) {
      setError(e?.response?.data?.detail || e.message)
    }
  }

  return (
    <div className="relative" ref={boxRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Switch dataset"
        className="flex max-w-[15rem] items-center gap-1.5 rounded border border-zinc-300 px-2.5 py-1.5 text-xs text-zinc-700 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-500"
      >
        <DatabaseIcon className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
        <span className="truncate">{active?.name || 'No dataset'}</span>
        <ChevronDownIcon className="h-3 w-3 shrink-0 text-zinc-500" />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-96 rounded-lg border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-900">
          <div className="border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
            <p className="text-[11px] font-semibold tracking-wider text-zinc-500">
              UPLOADED DATASETS
            </p>
            <p className="mt-0.5 text-[10px] text-zinc-500">
              Every upload is kept. Switch to any of them and its detection runs come
              back with it.
            </p>
          </div>

          {error && (
            <p className="border-b border-zinc-200 px-3 py-2 text-[11px] text-red-600 dark:border-zinc-800 dark:text-red-400">
              {error}
            </p>
          )}

          <div className="max-h-80 overflow-y-auto">
            {datasets.length === 0 && (
              <p className="px-3 py-4 text-xs text-zinc-500">
                Nothing uploaded yet. Use Upload CSV.
              </p>
            )}

            {datasets.map((dataset) => (
              <div
                key={dataset.id}
                className={`group flex items-start gap-2 border-b border-zinc-200/70 px-3 py-2.5 last:border-0 dark:border-zinc-800/70 ${
                  dataset.is_active ? 'bg-green-50/60 dark:bg-green-950/20' : ''
                }`}
              >
                <div className="min-w-0 flex-1">
                  {editing === dataset.id ? (
                    <input
                      autoFocus
                      value={draftName}
                      onChange={(e) => setDraftName(e.target.value)}
                      onBlur={() => handleRename(dataset.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleRename(dataset.id)
                        if (e.key === 'Escape') setEditing(null)
                      }}
                      className="w-full rounded border border-zinc-300 bg-white px-1.5 py-0.5 text-xs text-zinc-900 outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
                    />
                  ) : (
                    <div className="flex min-w-0 items-center gap-1">
                      <button
                        onClick={() => !dataset.is_active && handleActivate(dataset.id)}
                        disabled={busy}
                        title={dataset.is_active ? dataset.name : 'Switch to this dataset'}
                        className="block min-w-0 flex-1 truncate text-left text-xs font-medium text-zinc-900 disabled:opacity-50 dark:text-zinc-100"
                      >
                        {dataset.name}
                        {dataset.is_active && (
                          <span className="ml-1.5 rounded bg-green-100 px-1 py-0.5 text-[9px] font-semibold text-green-700 dark:bg-green-900/60 dark:text-green-300">
                            ACTIVE
                          </span>
                        )}
                      </button>
                      <button
                        onClick={() => {
                          setEditing(dataset.id)
                          setDraftName(dataset.name)
                        }}
                        title="Rename"
                        className="shrink-0 rounded p-1 text-zinc-400 opacity-0 transition-opacity hover:bg-zinc-100 hover:text-zinc-700 group-hover:opacity-100 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                      >
                        <EditIcon className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                  <div className="mt-0.5 text-[10px] text-zinc-500">
                    {dataset.company_count} companies · {dataset.invoice_count} invoices ·{' '}
                    {dataset.run_count} run{dataset.run_count === 1 ? '' : 's'}
                  </div>
                  <div className="text-[10px] text-zinc-400 dark:text-zinc-600">
                    {when(dataset.uploaded_at)}
                    {dataset.uploaded_by_name && ` · ${dataset.uploaded_by_name}`}
                  </div>
                </div>

                <button
                  onClick={() => handleDelete(dataset)}
                  disabled={busy}
                  title="Delete this dataset"
                  className="mt-0.5 shrink-0 rounded p-1 text-zinc-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                >
                  <TrashIcon className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

import { type ReactNode, useState } from 'react'

import GapAnalysisPage from './pages/gap-analysis/index'
import ResumeTailorPage from './pages/resume-tailor/index'

type AppView = 'tailor' | 'gaps'

function NavTab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? 'rounded-md bg-violet-100 px-3 py-2 text-sm font-medium text-violet-900 dark:bg-violet-950/60 dark:text-violet-100'
          : 'rounded-md px-3 py-2 text-sm font-medium text-zinc-600 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100'
      }
    >
      {children}
    </button>
  )
}

export default function App() {
  const [view, setView] = useState<AppView>('gaps')

  return (
    <>
      <nav className="sticky top-0 z-10 border-b border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-2">
          <span className="mr-2 text-sm font-semibold tracking-tight text-zinc-800 dark:text-zinc-100">
            Resume Refining &amp; Tailoring
          </span>
          <span className="hidden text-zinc-300 dark:text-zinc-600 sm:inline" aria-hidden>
            |
          </span>
          <div className="flex gap-1">
            <NavTab active={view === 'gaps'} onClick={() => setView('gaps')}>
              Refinery
            </NavTab>
            <NavTab active={view === 'tailor'} onClick={() => setView('tailor')}>
              Tailor
            </NavTab>
          </div>
        </div>
      </nav>
      {view === 'tailor' ? <ResumeTailorPage /> : <GapAnalysisPage />}
    </>
  )
}

import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { EvaluationRun, TestResult } from '../types/api'

export function useEvaluationReport(id: number) {
  const [run, setRun] = useState<EvaluationRun | null>(null)
  const [results, setResults] = useState<TestResult[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    let shouldPoll = false
    let timer: number | undefined
    let controller: AbortController | undefined
    setRun(null)
    setResults([])
    setLoading(true)
    setError('')

    async function load() {
      if (!Number.isInteger(id) || id < 1) {
        setError('This evaluation ID is not valid.')
        setLoading(false)
        return
      }
      controller = new AbortController()
      setRefreshing(true)
      try {
        const [nextRun, nextResults] = await Promise.all([
          api.getEvaluation(id, controller.signal),
          api.getEvaluationResults(id, controller.signal),
        ])
        if (!active) return
        setRun(nextRun)
        setResults(nextResults)
        setError('')
        shouldPoll = nextRun.status === 'pending' || nextRun.status === 'running'
      } catch (failure) {
        controller.abort()
        if (active) setError(failure instanceof Error ? failure.message : 'Unable to load the report.')
      } finally {
        if (active) {
          setLoading(false)
          setRefreshing(false)
          // Schedule after completion, even after failure; never overlap polls.
          if (shouldPoll) timer = window.setTimeout(() => void load(), 2_500)
        }
      }
    }
    void load()
    return () => {
      active = false
      window.clearTimeout(timer)
      controller?.abort()
    }
  }, [id, attempt])

  return { run, results, loading, refreshing, error, retry: () => setAttempt((value) => value + 1) }
}

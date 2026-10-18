// Independent helper for the frontend developer; importing it does not change the UI.
// Pass the jury key at runtime. Do not bake it into a public VITE_* variable.
export function createAnalysisClient({ apiKey, baseUrl = '' }) {
  const root = baseUrl.replace(/\/$/, '')

  async function request(path, { signal, ...options } = {}) {
    const response = await fetch(`${root}/api/v1${path}`, {
      ...options,
      signal,
      headers: { ...options.headers, 'X-API-Key': apiKey },
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      const error = new Error(
        typeof data.detail === 'string' ? data.detail : `Ошибка API: ${response.status}`,
      )
      error.status = response.status
      throw error
    }
    return data
  }

  return {
    capabilities: (signal) => request('/capabilities', { signal }),
    rules: (signal) => request('/rules', { signal }),
    async analyze(file, signal) {
      const body = new FormData()
      body.append('file', file)
      return request('/analyze', { method: 'POST', body, signal })
    },
    getJob: (jobId, signal) => request(`/jobs/${encodeURIComponent(jobId)}`, { signal }),
    async waitForJob(jobId, { signal, onUpdate = () => {}, intervalMs = 1500 } = {}) {
      const deadline = Date.now() + 290_000
      while (Date.now() < deadline) {
        const job = await request(`/jobs/${encodeURIComponent(jobId)}`, { signal })
        onUpdate(job)
        if (job.status === 'done') return job
        if (job.status === 'failed') {
          const error = new Error(job.error?.message || 'Не удалось обработать видео')
          error.code = job.error?.code
          throw error
        }
        await new Promise((resolve, reject) => {
          function abort() {
            clearTimeout(timer)
            reject(signal.reason || new DOMException('Aborted', 'AbortError'))
          }
          const timer = setTimeout(() => {
            signal?.removeEventListener('abort', abort)
            resolve()
          }, intervalMs)
          if (signal?.aborted) abort()
          else signal?.addEventListener('abort', abort, { once: true })
        })
      }
      throw new Error('Истекло время ожидания. Проверьте статус задания повторно.')
    },
  }
}

import { useEffect, useRef, useState } from 'react'
import { createAnalysisClient } from './api/analysis'
import AnalysisResult from './components/AnalysisResult'
import './App.css'

const DEFAULT_EXTENSIONS = ['.mov', '.mp4', '.m4v', '.avi']
const STAGE_LABELS = {
  queued: 'Ожидание обработки',
  validating: 'Проверка видео',
  analyzing: 'Анализ видео',
  extracting_evidence: 'Подготовка кадров',
  completed: 'Готово',
  failed: 'Ошибка обработки',
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 16V3m0 0L7.5 7.5M12 3l4.5 4.5" />
      <path d="M4 15.5v3A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5v-3" />
    </svg>
  )
}

function App() {
  const inputRef = useRef(null)
  const requestRef = useRef(null)
  const fileUrlRef = useRef('')
  const [file, setFile] = useState(null)
  const [fileUrl, setFileUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [capabilities, setCapabilities] = useState(null)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [job, setJob] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  useEffect(() => () => {
    requestRef.current?.abort()
    if (fileUrlRef.current) URL.revokeObjectURL(fileUrlRef.current)
  }, [])

  function setSelectedFile(nextFile) {
    if (fileUrlRef.current) URL.revokeObjectURL(fileUrlRef.current)
    fileUrlRef.current = nextFile ? URL.createObjectURL(nextFile) : ''
    setFileUrl(fileUrlRef.current)
    setFile(nextFile)
  }

  async function connect() {
    const key = apiKey.trim()
    if (!key) {
      setError('Введите API-ключ для подключения к серверу.')
      return
    }
    setError('')
    setIsConnecting(true)
    try {
      const client = createAnalysisClient({ apiKey: key })
      const [nextCapabilities] = await Promise.all([
        client.capabilities(),
        client.rules(),
      ])
      setCapabilities(nextCapabilities)
      if (file && file.size > nextCapabilities.max_upload_bytes) {
        setSelectedFile(null)
        if (inputRef.current) inputRef.current.value = ''
        setError(`Размер видео превышает лимит сервера (${formatBytes(nextCapabilities.max_upload_bytes)}).`)
      }
    } catch (requestError) {
      setCapabilities(null)
      setError(requestError.message || 'Не удалось подключиться к серверу.')
    } finally {
      setIsConnecting(false)
    }
  }

  function selectFile(nextFile) {
    if (!nextFile) return
    const extensions = capabilities?.accepted_extensions || DEFAULT_EXTENSIONS
    if (!extensions.some((extension) => nextFile.name.toLowerCase().endsWith(extension))) {
      setError(`Поддерживаются форматы ${extensions.join(', ')}.`)
      setSelectedFile(null)
      return
    }
    if (capabilities && nextFile.size > capabilities.max_upload_bytes) {
      setError(`Размер видео превышает лимит сервера (${formatBytes(capabilities.max_upload_bytes)}).`)
      setSelectedFile(null)
      return
    }
    setSelectedFile(nextFile)
    setJob(null)
    setResult(null)
    setError('')
  }

  function handleDrop(event) {
    event.preventDefault()
    setIsDragging(false)
    selectFile(event.dataTransfer.files[0])
  }

  function clearFile() {
    setSelectedFile(null)
    setJob(null)
    setResult(null)
    setError('')
    if (inputRef.current) inputRef.current.value = ''
  }

  async function analyzeVideo() {
    if (!file || !capabilities || !apiKey.trim()) return
    const controller = new AbortController()
    requestRef.current = controller
    setError('')
    setResult(null)
    setJob({ status: 'processing', stage: 'queued', progress: 0 })
    setIsAnalyzing(true)
    const client = createAnalysisClient({ apiKey: apiKey.trim() })
    try {
      const accepted = await client.analyze(file, controller.signal)
      const completed = await client.waitForJob(accepted.job_id, {
        signal: controller.signal,
        onUpdate: setJob,
      })
      setJob(completed)
      setResult(completed)
    } catch (requestError) {
      if (requestError.name !== 'AbortError') setError(requestError.message || 'Не удалось выполнить анализ.')
    } finally {
      requestRef.current = null
      setIsAnalyzing(false)
    }
  }

  const extensions = capabilities?.accepted_extensions || DEFAULT_EXTENSIONS
  const isConnected = Boolean(capabilities)
  const canAnalyze = isConnected && (capabilities.mode === 'demo' || capabilities.model_available)
  const activeStep = result ? 3 : isAnalyzing || job ? 2 : file ? 1 : 0

  return (
    <div className={`page-shell${result ? ' has-results' : ''}`}>
      <header className="site-header">
        <div className="header-content">
          <div className="brand" aria-label="ForteBank — Контроль кассовой дисциплины">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 32 32" fill="none">
                <path d="M11 5H7a2 2 0 0 0-2 2v4m16-6h4a2 2 0 0 1 2 2v4M5 21v4a2 2 0 0 0 2 2h4m16-6v4a2 2 0 0 1-2 2h-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <path d="m13 11 8 5-8 5V11Z" fill="currentColor" />
              </svg>
            </span>
            <span className="brand-copy">
              <span className="brand-name">Forte<span>Scan</span></span>
              <span className="brand-description">Контроль кассовой дисциплины</span>
            </span>
          </div>
          <button className="help-link" type="button" onClick={() => setShowHelp(true)}>
            <span className="help-icon" aria-hidden="true">?</span> Как это работает
          </button>
        </div>
      </header>

      <main className={`main-content${result ? ' has-results' : ''}`}>
        {!result && <>
        <h1>Проверка видео кассира</h1>
        <p className="intro">
          Подключитесь к серверу и загрузите запись для анализа — результат подскажет, что проверить вручную.
        </p>

        <section className="connection-panel" aria-label="Подключение к серверу">
          <label htmlFor="api-key">API-ключ</label>
          <div className="connection-controls">
            <input
              id="api-key"
              type="password"
              value={apiKey}
              onChange={(event) => {
                setApiKey(event.target.value)
                setCapabilities(null)
                setError('')
              }}
              placeholder="Введите ключ из локального .env"
              autoComplete="off"
              disabled={isAnalyzing || isConnecting}
            />
            <button className="secondary-button" type="button" onClick={connect} disabled={isConnecting || isAnalyzing}>
              {isConnecting ? 'Подключение…' : isConnected ? 'Обновить подключение' : 'Подключиться'}
            </button>
          </div>
          <p className={`connection-status${isConnected ? ' is-connected' : ''}`} role="status">
            {isConnected
              ? capabilities.mode === 'demo'
                ? `Подключено · DEMO, тестовые результаты · лимит ${formatBytes(capabilities.max_upload_bytes)}`
                : capabilities.model_available
                  ? `Подключено · режим ML · лимит ${formatBytes(capabilities.max_upload_bytes)}`
                  : 'Сервер подключён, но ML-модель или её зависимости недоступны.'
              : 'Ключ используется только в этой вкладке и не сохраняется.'}
          </p>
        </section>

        <div
          className={`upload-zone${isDragging ? ' is-dragging' : ''}${error ? ' has-error' : ''}`}
          onDragEnter={(event) => { event.preventDefault(); setIsDragging(true) }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            event.preventDefault()
            if (!event.currentTarget.contains(event.relatedTarget)) setIsDragging(false)
          }}
          onDrop={handleDrop}
        >
          <input
            ref={inputRef}
            className="visually-hidden"
            type="file"
            accept={extensions.join(',')}
            onChange={(event) => selectFile(event.target.files[0])}
            aria-label={`Выбрать видео в форматах ${extensions.join(', ')}`}
            disabled={!canAnalyze || isAnalyzing}
          />
          <div className="upload-icon"><UploadIcon /></div>
          {file ? (
            <>
              <h2>Видео выбрано</h2>
              <p className="upload-subtitle file-name">{file.name}</p>
              <p className="file-hint">{formatBytes(file.size)}</p>
              <button className="primary-button" type="button" onClick={analyzeVideo} disabled={isAnalyzing || !canAnalyze}>
                {isAnalyzing ? 'Обработка…' : result ? 'Запустить анализ снова' : 'Начать анализ'}
              </button>
              <button className="secondary-button file-change" type="button" onClick={() => inputRef.current?.click()} disabled={isAnalyzing}>
                Выбрать другое
              </button>
              <button className="remove-button" type="button" onClick={clearFile} disabled={isAnalyzing}>Удалить файл</button>
            </>
          ) : (
            <>
              <h2>Перетащите видео сюда</h2>
              <p className="upload-subtitle">{!isConnected ? 'Сначала подключитесь к серверу' : !canAnalyze ? 'Подключите ML-модуль на сервере' : 'или выберите файл на компьютере'}</p>
              <button className="primary-button" type="button" onClick={() => inputRef.current?.click()} disabled={!canAnalyze}>
                Выбрать видео
              </button>
              <p className="file-hint">{`Форматы ${extensions.join(', ')}${capabilities ? ` · до ${formatBytes(capabilities.max_upload_bytes)}` : ''}`}</p>
            </>
          )}
          {error && <p className="upload-error" role="alert">{error}</p>}
        </div>

        {isAnalyzing && job && (
          <section className="progress-panel" aria-live="polite">
            <div className="progress-heading"><strong>{STAGE_LABELS[job.stage] || 'Обработка видео'}</strong><span>{job.progress}%</span></div>
            <progress max="100" value={job.progress} aria-label="Прогресс анализа" />
            <p>Не закрывайте страницу до завершения обработки.</p>
          </section>
        )}
        </>}

        {result && <AnalysisResult key={result.job_id} result={result} fileUrl={fileUrl} fileName={file?.name} onReset={clearFile} />}

        {!result && <ol className="steps" aria-label="Этапы проверки">
          {['Загрузка', 'Анализ', 'Результат'].map((label, index) => (
            <li className={activeStep >= index + 1 ? 'current' : ''} key={label}><span>{index + 1}</span>{label}</li>
          ))}
        </ol>}
      </main>

      <footer className="site-footer">
        Видео обрабатывается локально. Результат — подсказка для проверки человеком, а не окончательное заключение.
      </footer>

      {showHelp && (
        <div className="dialog-backdrop" onClick={() => setShowHelp(false)}>
          <section className="help-dialog" role="dialog" aria-modal="true" aria-labelledby="help-title" onClick={(event) => event.stopPropagation()}>
            <button className="dialog-close" type="button" aria-label="Закрыть" onClick={() => setShowHelp(false)}>×</button>
            <h2 id="help-title">Как это работает</h2>
            <p>Введите API-ключ сервера, затем выберите видео в одном из поддерживаемых форматов. Видео отправляется на настроенный backend для обработки.</p>
            <p>Результат помогает обратить внимание на эпизоды, но не является окончательным заключением. Режим DEMO возвращает тестовый результат.</p>
          </section>
        </div>
      )}
    </div>
  )
}

function formatBytes(bytes) {
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(1)} ГБ`
  return `${Math.round(bytes / 1_000_000)} МБ`
}

export default App

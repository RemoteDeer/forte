import { useEffect, useRef, useState } from 'react'

function PlayIcon() {
  return <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path d="M6 3.8a1 1 0 0 1 1.5-.86l9 5.2a1 1 0 0 1 0 1.72l-9 5.2A1 1 0 0 1 6 14.2Z" /></svg>
}

function formatTime(seconds) {
  const hundredths = Math.round(seconds * 100)
  return `${String(Math.floor(hundredths / 6000)).padStart(2, '0')}:${((hundredths % 6000) / 100).toFixed(2).padStart(5, '0')}`
}

const DEMO_DESCRIPTIONS = {
  R01: 'Пример: деньги убраны без видимого пересчёта.',
  R02: 'Пример: пересчёт начат после ухода клиента.',
}

export default function AnalysisResult({ result, fileUrl, fileName, onReset }) {
  const videoRef = useRef(null)
  const timelineRef = useRef(null)
  const detailsRef = useRef(null)
  const episodeListRef = useRef(null)
  const pendingSeekRef = useRef(null)
  const modeRef = useRef('full')
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const [selectedRange, setSelectedRange] = useState(null)
  const [playbackMode, setPlaybackMode] = useState('full')
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackNote, setPlaybackNote] = useState('')
  const [mediaError, setMediaError] = useState(false)
  const [mediaDuration, setMediaDuration] = useState(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [rangeError, setRangeError] = useState('')
  const [timelineWidth, setTimelineWidth] = useState(600)
  const isDemo = result.mode === 'demo'
  const episodes = result.violations.map(episode => isDemo ? {
    ...episode,
    type: episode.rule.title,
    description: DEMO_DESCRIPTIONS[episode.rule.id] || 'Пример эпизода для проверки.',
  } : episode).sort((a, b) => a.timecode_sec - b.timecode_sec)
  const selectedEpisode = episodes[selectedIndex]
  const duration = mediaDuration ?? result.duration_sec ?? 0
  const activeRange = selectedRange && {
    ...selectedRange,
    start: duration > 0 ? Math.min(selectedRange.start, Math.max(0, duration - 0.001)) : selectedRange.start,
    end: duration > 0 ? Math.min(selectedRange.end, duration) : selectedRange.end,
  }

  useEffect(() => {
    const track = timelineRef.current
    if (!track || !window.ResizeObserver) return
    const observer = new window.ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width
      if (width > 0) setTimelineWidth(width)
    })
    observer.observe(track)
    return () => observer.disconnect()
  }, [duration, fileUrl])

  useEffect(() => {
    const list = episodeListRef.current
    const row = list?.querySelector(`[data-episode-index="${selectedIndex}"]`)
    if (!row) return
    if (row.offsetHeight > list.clientHeight) {
      if (row.offsetTop < list.scrollTop || row.offsetTop >= list.scrollTop + list.clientHeight) {
        list.scrollTop = row.offsetTop
      }
      return
    }
    const bottom = row.offsetTop + row.offsetHeight
    if (row.offsetTop < list.scrollTop) list.scrollTop = row.offsetTop
    else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight
  }, [selectedIndex])

  // Keep close timestamps individually clickable; nudge their labels side by side.
  const markerWidth = 28
  const markerGap = 34
  const markersPerRow = Math.max(1, Math.floor(timelineWidth / markerGap))
  const timelineMarkers = []
  for (let offset = 0; offset < episodes.length; offset += markersPerRow) {
    const row = episodes.slice(offset, offset + markersPerRow)
    const positions = row.map(episode => Math.max(markerWidth / 2,
      Math.min(timelineWidth - markerWidth / 2, episode.timecode_sec / (duration || 1) * timelineWidth)))
    for (let index = 1; index < positions.length; index++) {
      positions[index] = Math.max(positions[index], positions[index - 1] + markerGap)
    }
    if (positions.length) positions[positions.length - 1] = Math.min(positions.at(-1), timelineWidth - markerWidth / 2)
    for (let index = positions.length - 2; index >= 0; index--) {
      positions[index] = Math.min(positions[index], positions[index + 1] - markerGap)
    }
    positions.forEach((position, index) => timelineMarkers.push({
      index: offset + index, left: position / timelineWidth * 100, row: Math.floor(offset / markersPerRow),
    }))
  }
  const markerRows = Math.max(1, Math.ceil(episodes.length / markersPerRow))

  function setMode(mode) {
    // Media events may fire before React commits the next render.
    modeRef.current = mode
    setPlaybackMode(mode)
  }

  function playVideo() {
    if (mediaError || !videoRef.current) return
    setPlaybackNote('')
    videoRef.current.play().catch(() => {
      setPlaybackNote('Воспроизведение не началось. Нажмите «Всё видео» или «Смотреть эпизод» повторно.')
    })
  }

  function applyPendingSeek() {
    const video = videoRef.current
    const seconds = pendingSeekRef.current
    if (!video || seconds == null || video.readyState < 1) return
    try {
      video.currentTime = Number.isFinite(video.duration)
        ? Math.min(seconds, Math.max(0, video.duration - 0.001)) : seconds
      setCurrentTime(video.currentTime)
      pendingSeekRef.current = null
      playVideo()
    } catch {
      setPlaybackNote('Не удалось перейти к фрагменту. Проверьте кадры-доказательства рядом с видео.')
    }
  }

  function selectEpisode(index, evidenceTime = null) {
    const episode = episodes[index]
    if (!episode) return
    const hasRange = Number.isFinite(episode.start_sec) && Number.isFinite(episode.end_sec)
      && episode.start_sec <= episode.timecode_sec && episode.end_sec > episode.timecode_sec
    const range = {
      start: Math.max(0, hasRange ? episode.start_sec : episode.timecode_sec - 1),
      end: Math.min(duration || Infinity, hasRange ? episode.end_sec : episode.timecode_sec + 1),
      source: hasRange ? 'model' : 'context',
    }
    if (evidenceTime != null && (evidenceTime < range.start || evidenceTime >= range.end)) {
      range.start = Math.min(range.start, evidenceTime)
      range.end = Math.min(duration || Infinity, Math.max(range.end, evidenceTime + 0.001))
      range.source = 'evidence'
    }
    setSelectedIndex(index)
    if (detailsRef.current) detailsRef.current.scrollTop = 0
    setSelectedRange(range)
    setMode('clip')
    setRangeError('')
    pendingSeekRef.current = evidenceTime ?? range.start
    if (!mediaError) applyPendingSeek()
    // Keep the chosen row in place: the player and its explanation never scroll away.
  }

  function fullPlayback() {
    const video = videoRef.current
    if (!video || mediaError) return
    pendingSeekRef.current = null
    if (modeRef.current === 'full' && !video.paused) {
      video.pause()
      return
    }
    setMode('full')
    if (video.ended) video.currentTime = 0
    playVideo()
  }

  function replayRange() {
    if (!activeRange || mediaError) return
    setMode('clip')
    pendingSeekRef.current = activeRange.start
    applyPendingSeek()
  }

  function updatePlaybackTime() {
    const video = videoRef.current
    if (!video) return
    let time = Math.max(0, Math.min(video.currentTime, duration || Infinity))
    if (video.currentTime !== time) video.currentTime = time
    if (modeRef.current === 'clip' && activeRange) {
      if (time < activeRange.start) {
        video.currentTime = activeRange.start
        time = activeRange.start
      }
      if (time >= activeRange.end) {
        video.pause()
        if (time > activeRange.end) video.currentTime = activeRange.end
        time = activeRange.end
      }
    }
    setCurrentTime(time)
  }

  function changeBoundary(edge, value) {
    if (value === '' || !activeRange) return
    const range = { ...activeRange, [edge]: Number(value), source: 'manual' }
    if (!Number.isFinite(range[edge]) || range.start < 0 || range.end > duration || range.start >= range.end) {
      setRangeError('Начало должно быть раньше конца, обе границы — в пределах видео.')
      return
    }
    setSelectedRange(range)
    setRangeError('')
    const video = videoRef.current
    if (video && modeRef.current === 'clip' && (video.currentTime < range.start || video.currentTime >= range.end)) {
      video.pause()
      video.currentTime = range.start
      setCurrentTime(range.start)
    }
  }

  return (
    <section className="result-panel review-workspace" aria-label="Просмотр результатов анализа">
      <div className="result-heading">
        <h2 title={fileName}>Анализ · {fileName || 'Видео'}</h2>
        <button className="new-video-button" type="button" onClick={onReset}><span aria-hidden="true">＋</span> Новое видео</button>
      </div>

      <div className="review-grid">
        <section className="video-review" aria-label="Единый видеоплеер">
          {fileUrl ? (
            <div className="annotated-player">
              <video
                ref={videoRef}
                id="source-video"
                className="source-video"
                src={fileUrl}
                preload="metadata"
                playsInline
                tabIndex={0}
                aria-label={`Исходное видео · ${playbackMode === 'clip' ? 'фрагмент' : 'вся запись'}. Нажмите для воспроизведения всей записи`}
                onClick={fullPlayback}
                onKeyDown={event => {
                  if (event.key === ' ' || event.key === 'Enter') {
                    event.preventDefault()
                    fullPlayback()
                  }
                }}
                onLoadedMetadata={() => {
                  if (Number.isFinite(videoRef.current.duration)) setMediaDuration(videoRef.current.duration)
                  applyPendingSeek()
                }}
                onCanPlay={applyPendingSeek}
                onTimeUpdate={updatePlaybackTime}
                onSeeked={updatePlaybackTime}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onEnded={() => setIsPlaying(false)}
                onError={() => {
                  pendingSeekRef.current = null
                  setMediaError(true)
                }}
              />
              <div className="player-controls">
                <div className="player-actions">
                <button className="player-full-play" type="button" onClick={fullPlayback} disabled={mediaError} aria-label={isPlaying && playbackMode === 'full' ? 'Приостановить видео' : 'Воспроизвести всё видео'}>
                  {isPlaying && playbackMode === 'full' ? <span aria-hidden="true">Ⅱ</span> : <PlayIcon />}
                  {isPlaying && playbackMode === 'full' ? 'Пауза' : 'Всё видео'}
                </button>
                {isPlaying && playbackMode === 'clip' && <button className="player-pause" type="button" onClick={() => videoRef.current.pause()} aria-label="Приостановить фрагмент">Ⅱ Пауза</button>}
                </div>
                <span className="player-clock">{formatTime(currentTime)} / {formatTime(duration)}</span>
              </div>
              {duration > 0 && (
                <div className="player-timeline" aria-label="Шкала видео с отметками эпизодов">
                  <div className="timeline-track" ref={timelineRef}>
                    <div className="timeline-progress" style={{ width: `${Math.min(100, currentTime / duration * 100)}%` }} />
                    {activeRange && (
                      <div className={`timeline-selection${playbackMode === 'full' ? ' is-inactive' : ''}`} style={{ left: `${activeRange.start / duration * 100}%`, width: `${(activeRange.end - activeRange.start) / duration * 100}%` }} aria-hidden="true">
                        <span className="timeline-boundary start" /><span className="timeline-boundary end" />
                      </div>
                    )}
                    <input className="timeline-scrubber" type="range" min="0" max={duration} step="0.01" value={Math.max(0, Math.min(currentTime, duration))} aria-label="Позиция воспроизведения видео" aria-valuetext={formatTime(currentTime)} disabled={mediaError} onChange={event => {
                      setMode('full')
                      pendingSeekRef.current = null
                      videoRef.current.currentTime = Number(event.target.value)
                      setCurrentTime(Number(event.target.value))
                    }} />
                    <div className="timeline-markers">
                      {episodes.map((episode, index) => <span className="timeline-event-tick" key={`tick-${index}`} style={{ left: `${Math.max(0, Math.min(100, episode.timecode_sec / duration * 100))}%` }} aria-hidden="true" />)}
                      {timelineMarkers.map(marker => (
                        <button className={`timeline-marker${marker.index === selectedIndex ? ' is-selected' : ''}`} key={marker.index} type="button" style={{ left: `${marker.left}%`, top: `${19 + marker.row * markerGap}px` }} title={`#${marker.index + 1} · ${formatTime(episodes[marker.index].timecode_sec)} — ${episodes[marker.index].type}`} aria-label={`Эпизод ${marker.index + 1}: ${formatTime(episodes[marker.index].timecode_sec)}`} aria-controls="source-video episode-explanation" onClick={() => selectEpisode(marker.index)}>
                          {marker.index + 1}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="timeline-marker-space" style={{ height: `${47 + (markerRows - 1) * markerGap}px` }} aria-hidden="true" />
                </div>
              )}
            </div>
          ) : <p className="empty-result">Исходное видео недоступно. Используйте кадры-доказательства.</p>}
          {mediaError && <p className="playback-notice" role="alert">Браузер не смог воспроизвести кодек. Кадры-доказательства доступны в объяснении выбранного эпизода.</p>}
          {playbackNote && !mediaError && <p className="playback-notice" role="status">{playbackNote}</p>}
        </section>

        <aside className="review-details" ref={detailsRef} id="episode-explanation" aria-label="Объяснение выбранного эпизода">
          <div className="episode-detail-heading">
            <div>
              <p className="episode-number selected-moment" role="status">{selectedEpisode ? `Нарушение ${selectedIndex + 1}` : 'Нарушения'}</p>
              {selectedEpisode && <h3>{selectedEpisode.type}</h3>}
            </div>
            {episodes.length > 1 && <nav className="episode-pagination" aria-label="Переключение нарушений"><button className="secondary-button" type="button" disabled={selectedIndex <= 0} onClick={() => selectEpisode(selectedIndex - 1)} aria-label="Предыдущий эпизод">←</button><button className="secondary-button" type="button" disabled={selectedIndex >= episodes.length - 1} onClick={() => selectEpisode(selectedIndex + 1)} aria-label="Следующий эпизод">→</button></nav>}
          </div>
          {selectedEpisode ? (
            <>
              <p className="episode-description">{selectedEpisode.description.split('\nОснование для проверки:')[0]}</p>
              {fileUrl && <button className="timecode-button clip-play" type="button" onClick={replayRange} disabled={mediaError}><PlayIcon /> Смотреть эпизод {activeRange && `${formatTime(activeRange.start)} — ${formatTime(activeRange.end)}`}</button>}
              {activeRange && (
                <details className="range-panel">
                  <summary>Изменить границы</summary>
                  <p className="range-source">{activeRange.source === 'model' ? 'Границы переданы моделью.' : activeRange.source === 'manual' ? 'Границы заданы вручную.' : activeRange.source === 'evidence' ? 'Окно расширено до выбранного кадра.' : 'Контекст ±1 с. Это окно просмотра, а не установленная длительность нарушения.'}</p>
                  <div className="range-controls">
                    <label>Начало, с<input aria-label="Начало диапазона, секунды" type="number" min="0" max={activeRange.end} step="0.1" value={Number(activeRange.start.toFixed(3))} onChange={event => changeBoundary('start', event.target.value)} /></label>
                    <label>Конец, с<input aria-label="Конец диапазона, секунды" type="number" min={activeRange.start} max={duration} step="0.1" value={Number(activeRange.end.toFixed(3))} onChange={event => changeBoundary('end', event.target.value)} /></label>
                  </div>
                  {rangeError && <p className="playback-notice" role="alert">{rangeError}</p>}
                </details>
              )}
              <div className="rule-detail">
                <strong>{selectedEpisode.rule.title}</strong>
                <span>{selectedEpisode.rule.document}{selectedEpisode.rule.section && ` · ${selectedEpisode.rule.section}`}</span>
                {selectedEpisode.rule.url && <a href={selectedEpisode.rule.url} target="_blank" rel="noreferrer">Открыть источник правила ↗</a>}
              </div>
              {selectedEpisode.evidence_frames.length > 0 && (
                <div className="evidence-grid">
                  {selectedEpisode.evidence_frames.map((frame, index) => (
                    <figure key={`${frame.timestamp_sec}-${index}`}>
                      <img src={`data:image/jpeg;base64,${frame.image_base64}`} alt={`Кадр эпизода ${selectedIndex + 1}, ${formatTime(frame.timestamp_sec)}`} />
                      <figcaption>{fileUrl ? <button className="frame-timecode" type="button" onClick={() => selectEpisode(selectedIndex, frame.timestamp_sec)}><PlayIcon /> {formatTime(frame.timestamp_sec)}</button> : formatTime(frame.timestamp_sec)}</figcaption>
                    </figure>
                  ))}
                </div>
              )}
              {(selectedEpisode.rule.limitation || selectedEpisode.alternative_explanation || selectedEpisode.missing_data.length > 0) && (
                <details className="episode-caveats"><summary>Оговорки и недостающие данные</summary>
                  {selectedEpisode.rule.limitation && <p>{selectedEpisode.rule.limitation}</p>}
                  {selectedEpisode.alternative_explanation && <p>{selectedEpisode.alternative_explanation}</p>}
                  {selectedEpisode.missing_data.length > 0 && <p>{selectedEpisode.missing_data.join('; ')}</p>}
                </details>
              )}
            </>
          ) : (
            <div className="explanation-placeholder"><PlayIcon /><h3>{episodes.length ? 'Выберите нарушение' : 'Нарушений не найдено'}</h3>{episodes.length > 0 && <p>Нажмите номер на шкале или в списке снизу.</p>}</div>
          )}
        </aside>
      </div>

      <section className="episode-browser" aria-label="Все эпизоды">
        <div className="episode-browser-heading"><h3>Все нарушения <span>{episodes.length}</span></h3></div>
        {episodes.length ? <div className="violation-list" ref={episodeListRef}>
          {episodes.map((episode, index) => (
            <button className={`violation-item episode-jump${selectedIndex === index ? ' is-active' : ''}`} data-episode-index={index} type="button" key={`${episode.rule.id}-${episode.timecode_sec}-${index}`} aria-pressed={selectedIndex === index} aria-controls="source-video episode-explanation" aria-describedby={`episode-summary-${index}`} aria-label={`Смотреть эпизод ${index + 1}: ${episode.type}, с ${formatTime(episode.timecode_sec)}`} onClick={() => selectEpisode(index)}>
              <span className="episode-row-number">{index + 1}</span>
              <span className="episode-row-body">
                <strong>{episode.type}</strong>
                <span className="episode-row-description" id={`episode-summary-${index}`}>{episode.description.split('\nОснование для проверки:')[0]}</span>
                <span className="episode-row-rule">{episode.rule.document}{episode.rule.section && ` · ${episode.rule.section}`}</span>
                <span className="episode-row-time">{formatTime(episode.timecode_sec)} · {episode.rule.id}</span>
              </span>
              <PlayIcon />
            </button>
          ))}
        </div> : <p className="empty-result">Эпизодов для проверки нет.</p>}
      </section>
      <div className="review-footnote"><span>{isDemo ? 'Тестовые данные' : 'Требует проверки человеком'}</span>{result.limitations.length > 0 && <details className="limitations"><summary>Ограничения анализа</summary><ul>{result.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}</div>
    </section>
  )
}

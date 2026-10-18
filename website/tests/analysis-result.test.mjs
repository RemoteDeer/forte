import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { afterEach, beforeEach, test } from 'node:test'
import { JSDOM } from 'jsdom'
import { act, createElement } from 'react'
import { transformWithOxc } from 'vite'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window
globalThis.document = dom.window.document
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
window.matchMedia = () => ({ matches: false })
const { createRoot } = await import('react-dom/client')

// Compile the actual JSX with the same transformer as Vite; no browser or API needed.
const source = await readFile(new URL('../src/components/AnalysisResult.jsx', import.meta.url), 'utf8')
const compiled = await transformWithOxc(source, 'AnalysisResult.jsx', { jsx: { runtime: 'automatic' } })
const code = compiled.code
  .replaceAll('from "react"', `from ${JSON.stringify(import.meta.resolve('react'))}`)
  .replaceAll('from "react/jsx-runtime"', `from ${JSON.stringify(import.meta.resolve('react/jsx-runtime'))}`)
const componentUrl = `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const { default: AnalysisResult } = await import(componentUrl)

const rule = { id: 'R01', title: 'Правило', document: 'Источник', section: 'Пункт 1' }
function episode(type, seconds) {
  return {
    type, timecode_sec: seconds, description: `Наблюдение: ${type}`, rule,
    missing_data: [], evidence_frames: [{ timestamp_sec: seconds - 0.5, image_base64: '' }],
  }
}
// Same rule and timestamp deliberately occur twice: these are distinct episodes.
const result = {
  job_id: 'test', mode: 'plugin', verdict: 'violation', duration_sec: 120, limitations: [],
  violations: [episode('Поздний эпизод', 30), episode('Первый эпизод', 10), episode('Другой эпизод', 10)],
}

let root, container, readyState, playCalls, pauseCalls, scrolledElement, rejectPlayback, paused
beforeEach(() => {
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  readyState = 1
  paused = true
  playCalls = 0
  pauseCalls = 0
  rejectPlayback = false
  scrolledElement = null
  dom.window.HTMLElement.prototype.scrollIntoView = function () { scrolledElement = this }
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'readyState', { configurable: true, get: () => readyState })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'duration', { configurable: true, get: () => 120 })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'paused', { configurable: true, get: () => paused })
  dom.window.HTMLMediaElement.prototype.pause = function () {
    pauseCalls += 1
    paused = true
    this.dispatchEvent(new window.Event('pause'))
  }
  dom.window.HTMLMediaElement.prototype.play = function () {
    playCalls += 1
    if (rejectPlayback) return Promise.reject(new Error('Autoplay blocked'))
    paused = false
    this.dispatchEvent(new window.Event('play'))
    return Promise.resolve()
  }
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

async function render(analysis = result) {
  await act(async () => root.render(createElement(AnalysisResult, { result: analysis, fileUrl: 'blob:test', fileName: 'sample.mov', onReset() {} })))
}
async function click(element) {
  assert.ok(element, 'Expected a clickable control')
  await act(async () => element.click())
}
async function dispatch(element, name) {
  await act(async () => element.dispatchEvent(new window.Event(name)))
}
const rows = () => container.querySelectorAll('.episode-jump')
const video = () => container.querySelector('video')

test('one video and one seek bar serve the complete review workspace', async () => {
  await render()
  assert.equal(container.querySelectorAll('video').length, 1)
  assert.equal(video().controls, false, 'Do not display a second native seek bar')
  assert.equal(container.querySelectorAll('input[type="range"]').length, 1)
  assert.equal(rows().length, 3)
  assert.ok(container.querySelector('.review-details'))
  assert.match(video().getAttribute('aria-label'), /вся запись/)
})

test('selecting an episode plays its clip and shows only its explanation without scrolling', async () => {
  await render()
  container.querySelector('.review-details').scrollTop = 150
  await click(rows()[2])
  assert.equal(video().currentTime, 29)
  assert.equal(playCalls, 1)
  assert.equal(scrolledElement, null)
  assert.equal(container.querySelector('.review-details').scrollTop, 0)
  assert.equal(container.querySelectorAll('.episode-description').length, 1)
  assert.match(container.querySelector('.episode-description').textContent, /Поздний эпизод/)
  assert.equal(container.querySelector('.selected-moment').textContent, 'Нарушение 3')
  assert.match(video().getAttribute('aria-label'), /фрагмент/)
})

test('previous and next preserve distinct episodes even at equal timestamps', async () => {
  await render()
  const [previous, next] = container.querySelectorAll('.episode-pagination button')
  assert.equal(previous.disabled, true)
  await click(next)
  assert.equal(video().currentTime, 9)
  await click(next)
  assert.match(container.querySelector('.episode-description').textContent, /Другой эпизод/)
  await click(next)
  assert.equal(next.disabled, true)
  await click(previous)
  assert.match(container.querySelector('.episode-description').textContent, /Другой эпизод/)
  assert.equal(rows()[1].getAttribute('aria-pressed'), 'true')
})

test('a clip selected before metadata loads seeks only when ready', async () => {
  readyState = 0
  await render()
  await click(rows()[2])
  assert.equal(playCalls, 0)
  readyState = 1
  await dispatch(video(), 'loadedmetadata')
  assert.equal(video().currentTime, 29)
  assert.equal(playCalls, 1)
  await dispatch(video(), 'canplay')
  assert.equal(playCalls, 1)
})

test('evidence uses the same player and seeks to the exact frame', async () => {
  await render()
  await click(rows()[0])
  await click(container.querySelector('.frame-timecode'))
  assert.equal(video().currentTime, 9.5)
  assert.equal(container.querySelectorAll('video').length, 1)
  assert.equal(scrolledElement, null)
})

test('an unsupported codec retains the explanation and evidence', async () => {
  await render()
  await dispatch(video(), 'error')
  await click(rows()[0])
  assert.equal(playCalls, 0)
  assert.match(container.querySelector('[role="alert"]').textContent, /Кадры-доказательства/)
  assert.ok(container.querySelector('.episode-description'))
  assert.ok(container.querySelector('.evidence-grid img'))
  assert.equal(container.querySelector('.clip-play').disabled, true)
})

test('autoplay failure gives an actionable message', async () => {
  rejectPlayback = true
  await render()
  await click(rows()[0])
  assert.equal(video().currentTime, 9)
  assert.match(container.querySelector('.playback-notice').textContent, /повторно/)
})

test('coincident timestamps have adjacent individual buttons and open in one click', async () => {
  await render()
  const markers = container.querySelectorAll('.timeline-marker')
  assert.equal(markers.length, 3)
  assert.deepEqual([...markers].map(marker => marker.textContent.trim()), ['1', '2', '3'])
  assert.ok(parseFloat(markers[1].style.left) > parseFloat(markers[0].style.left))
  await click(markers[1])
  assert.equal(container.querySelectorAll('.timeline-boundary').length, 2)
  assert.match(container.querySelector('.episode-description').textContent, /Другой эпизод/)
  assert.equal(container.querySelector('.marker-choices'), null)
  assert.equal(scrolledElement, null)
})

test('close markers at the video end stay side by side inside the track', async () => {
  await render({ ...result, violations: [episode('Первый', 119), episode('Второй', 119.5), episode('Третий', 119.9)] })
  const markers = [...container.querySelectorAll('.timeline-marker')]
  const positions = markers.map(marker => parseFloat(marker.style.left))
  assert.ok(positions[0] >= 0)
  assert.ok(positions[2] <= 100)
  assert.ok(positions[1] - positions[0] >= 5.6)
  assert.ok(positions[2] - positions[1] >= 5.6)
  await click(markers[2])
  assert.match(container.querySelector('.episode-description').textContent, /Третий/)
  assert.equal(container.querySelectorAll('.timeline-event-tick').length, 3)
})

test('a dense timeline keeps every episode directly clickable without a grouped menu', async () => {
  const many = Array.from({ length: 30 }, (_, index) => episode(`Событие ${index + 1}`, 10))
  await render({ ...result, violations: many })
  const markers = container.querySelectorAll('.timeline-marker')
  assert.equal(markers.length, 30)
  assert.ok(parseFloat(markers[29].style.top) > parseFloat(markers[0].style.top))
  await click(markers[29])
  assert.match(container.querySelector('.episode-description').textContent, /Событие 30/)
  assert.equal(container.querySelector('.marker-choices'), null)
})

test('clip playback pauses at its end and can be replayed', async () => {
  await render()
  await click(rows()[0])
  video().currentTime = 14
  await dispatch(video(), 'timeupdate')
  assert.equal(video().currentTime, 11)
  assert.equal(pauseCalls, 1)
  assert.equal(container.querySelector('.range-ended'), null)
  await click(container.querySelector('.clip-play'))
  assert.equal(video().currentTime, 9)
  assert.equal(playCalls, 2)
})

test('clicking the video switches from clip to full playback while keeping the explanation', async () => {
  await render()
  await click(rows()[0])
  await click(video())
  assert.match(video().getAttribute('aria-label'), /вся запись/)
  video().currentTime = 40
  await dispatch(video(), 'timeupdate')
  assert.equal(video().currentTime, 40)
  assert.equal(pauseCalls, 0)
  assert.match(container.querySelector('.episode-description').textContent, /Первый эпизод/)
  assert.ok(container.querySelector('.timeline-selection.is-inactive'))
  // Explicit episode playback must re-enable the range.
  await click(container.querySelector('.clip-play'))
  video().currentTime = 40
  await dispatch(video(), 'timeupdate')
  assert.equal(video().currentTime, 11)
  assert.equal(pauseCalls, 1)
})

test('full-play control resumes past a completed clip boundary and can pause normally', async () => {
  await render()
  await click(rows()[0])
  video().currentTime = 11
  await dispatch(video(), 'timeupdate')
  await click(container.querySelector('.player-full-play'))
  video().currentTime = 60
  await dispatch(video(), 'timeupdate')
  assert.equal(video().currentTime, 60)
  assert.equal(paused, false)
  await click(container.querySelector('.player-full-play'))
  assert.equal(paused, true)
})

test('model bounds take precedence over context, and editing bounds preserves validation', async () => {
  await render({ ...result, violations: [{ ...episode('Диапазон модели', 10), start_sec: 2, end_sec: 19 }] })
  await click(rows()[0])
  assert.equal(video().currentTime, 2)
  const start = container.querySelector('[aria-label="Начало диапазона, секунды"]')
  assert.equal(start.value, '2')
  assert.equal(container.querySelector('[aria-label="Конец диапазона, секунды"]').value, '19')
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    setValue.call(start, '8')
    start.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  assert.equal(video().currentTime, 8)
  assert.match(container.querySelector('.range-source').textContent, /вручную/)
  await act(async () => {
    setValue.call(start, '25')
    start.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  assert.equal(start.value, '8')
  assert.match(container.querySelector('[role="alert"]').textContent, /раньше конца/)
})

test('context boundaries are clipped to the video end', async () => {
  await render({ ...result, violations: [episode('Конец видео', 119)] })
  await click(rows()[0])
  assert.equal(video().currentTime, 118)
  assert.equal(container.querySelector('[aria-label="Конец диапазона, секунды"]').value, '120')
})

test('scrubbing the main timeline returns to unrestricted full-video mode', async () => {
  await render()
  await click(rows()[0])
  const slider = container.querySelector('.timeline-scrubber')
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    setValue.call(slider, '80')
    slider.dispatchEvent(new window.Event('input', { bubbles: true }))
  })
  await dispatch(video(), 'seeked')
  assert.equal(video().currentTime, 80)
  assert.equal(pauseCalls, 0)
  assert.match(video().getAttribute('aria-label'), /вся запись/)
})

test('full-video selection cancels a pending clip seek before metadata loads', async () => {
  readyState = 0
  await render()
  await click(rows()[2])
  await click(video())
  readyState = 1
  await dispatch(video(), 'loadedmetadata')
  assert.equal(video().currentTime, 0, 'The old clip start must not be applied later')
  assert.match(video().getAttribute('aria-label'), /вся запись/)
})

test('keyboard activation on the video also selects full playback', async () => {
  await render()
  await click(rows()[0])
  await act(async () => video().dispatchEvent(new window.KeyboardEvent('keydown', { key: ' ', bubbles: true })))
  video().currentTime = 70
  await dispatch(video(), 'timeupdate')
  assert.equal(video().currentTime, 70)
  assert.equal(pauseCalls, 0)
})

test('the seek position and progress remain within the timeline at both endpoints', async () => {
  await render()
  video().currentTime = 125
  await dispatch(video(), 'timeupdate')
  assert.equal(video().currentTime, 120)
  assert.equal(container.querySelector('.timeline-scrubber').value, '120')
  assert.equal(container.querySelector('.timeline-progress').style.width, '100%')
  video().currentTime = -2
  await dispatch(video(), 'timeupdate')
  assert.equal(video().currentTime, 0)
  assert.equal(container.querySelector('.timeline-scrubber').value, '0')
  assert.equal(container.querySelector('.timeline-progress').style.width, '0%')
})

test('the review names the analysis and keeps navigation beside the selected violation', async () => {
  await render()
  assert.equal(container.querySelector('.result-heading h2').textContent, 'Анализ · sample.mov')
  assert.equal(container.querySelector('.result-eyebrow'), null)
  assert.equal(container.querySelector('.demo-warning'), null)
  assert.ok(container.querySelector('.new-video-button'))
  assert.equal(container.querySelector('.playback-mode'), null)
  assert.equal(container.querySelector('.timeline-labels'), null)
  assert.ok(container.querySelector('.player-actions .player-full-play'))
  await click(rows()[0])
  const heading = container.querySelector('.episode-detail-heading')
  assert.equal(heading.querySelector('.selected-moment').textContent, 'Нарушение 1')
  assert.ok(heading.querySelector('[aria-label="Следующий эпизод"]'))
  assert.equal(container.querySelector('.episode-browser .episode-pagination'), null)
  assert.equal(container.querySelector('.range-panel summary').textContent, 'Изменить границы')
  await click(heading.querySelector('[aria-label="Следующий эпизод"]'))
  assert.equal(heading.querySelector('.selected-moment').textContent, 'Нарушение 2')
})

test('all violations show their full explanations before selection and remain clickable', async () => {
  const longType = 'Полное название нарушения, которое должно переноситься на несколько строк без сокращения'
  const description = 'Первое наблюдаемое действие.\nВторое действие с полным объяснением причины проверки.'
  const analysis = { ...result, violations: [
    { ...episode(longType, 20), description, rule: { ...rule, document: 'Полное название нормативного документа', section: 'Пункт 19' } },
    { ...episode('Другое нарушение', 40), description: 'Второе нарушение также расписано полностью.' },
  ] }
  await render(analysis)
  const cards = rows()
  assert.equal(container.querySelectorAll('.episode-row-description').length, 2)
  assert.equal(cards[0].querySelector('strong').textContent, longType)
  assert.equal(cards[0].querySelector('.episode-row-description').textContent, description)
  assert.match(cards[0].querySelector('.episode-row-rule').textContent, /Полное название нормативного документа · Пункт 19/)
  assert.equal(cards[1].querySelector('.episode-row-description').textContent, 'Второе нарушение также расписано полностью.')
  const samePlayer = video()
  await click(cards[1])
  assert.equal(video(), samePlayer)
  assert.equal(video().currentTime, 39)
  assert.equal(container.querySelector('.episode-description').textContent, 'Второе нарушение также расписано полностью.')
  assert.equal(scrolledElement, null)
})

test('selecting a tall fully described card keeps its heading in view', async () => {
  await render()
  const list = container.querySelector('.violation-list')
  const first = rows()[0]
  Object.defineProperty(list, 'clientHeight', { configurable: true, value: 180 })
  Object.defineProperty(first, 'offsetHeight', { configurable: true, value: 300 })
  Object.defineProperty(first, 'offsetTop', { configurable: true, value: 0 })
  await click(first)
  assert.equal(list.scrollTop, 0, 'Do not jump to the bottom of a card taller than the list')
  assert.equal(scrolledElement, null)
})

test('legacy demo results get concise example explanations without integration boilerplate', async () => {
  const demoItem = {
    ...episode('Демонстрационный эпизод — проверка интеграции', 1),
    description: 'Тестовый эпизод для проверки API. Модель не запускалась.',
    rule: { ...rule, title: 'Пересчёт не наблюдается' },
  }
  await render({ ...result, mode: 'demo', violations: [demoItem] })
  await click(rows()[0])
  assert.equal(container.querySelector('.episode-detail-heading h3').textContent, 'Пересчёт не наблюдается')
  assert.equal(container.querySelector('.episode-description').textContent, 'Пример: деньги убраны без видимого пересчёта.')
  assert.doesNotMatch(container.textContent, /проверка интеграции|Модель не запускалась|Фрагмент завершён/)
  assert.match(container.querySelector('.review-footnote').textContent, /Тестовые данные/)
})

test('the completed analysis replaces the upload form with one persistent review player', async () => {
  const source = await readFile(new URL('../src/App.jsx', import.meta.url), 'utf8')
  const compiled = await transformWithOxc(source, 'App.jsx', { jsx: { runtime: 'automatic' } })
  const appCode = compiled.code
    .replaceAll('from "react"', `from ${JSON.stringify(import.meta.resolve('react'))}`)
    .replaceAll('from "react/jsx-runtime"', `from ${JSON.stringify(import.meta.resolve('react/jsx-runtime'))}`)
    .replace('from "./components/AnalysisResult"', `from ${JSON.stringify(componentUrl)}`)
    .replace('from "./api/analysis"', `from ${JSON.stringify(new URL('../src/api/analysis.js', import.meta.url).href)}`)
    .replace(/import "\.\/App\.css";?\n/, '')
  const { default: App } = await import(`data:text/javascript;base64,${Buffer.from(appCode).toString('base64')}`)
  const savedFetch = globalThis.fetch
  const savedCreate = URL.createObjectURL
  const savedRevoke = URL.revokeObjectURL
  globalThis.fetch = async url => {
    let data
    if (url.endsWith('/capabilities')) data = { mode: 'plugin', model_available: true, max_upload_bytes: 500000000, accepted_extensions: ['.mov'] }
    else if (url.endsWith('/rules')) data = [rule]
    else if (url.endsWith('/analyze')) data = { job_id: 'test' }
    else data = { ...result, status: 'done', stage: 'completed', progress: 100 }
    return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
  }
  URL.createObjectURL = () => 'blob:test'
  URL.revokeObjectURL = () => {}
  try {
    await act(async () => root.render(createElement(App)))
    const keyInput = container.querySelector('#api-key')
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    await act(async () => {
      setValue.call(keyInput, 'test-key-not-a-real-secret')
      keyInput.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
    await click(container.querySelector('.connection-controls button'))
    const fileInput = container.querySelector('input[type="file"]')
    Object.defineProperty(fileInput, 'files', { configurable: true, value: [new window.File(['test'], 'test.mov')] })
    await act(async () => fileInput.dispatchEvent(new window.Event('change', { bubbles: true })))
    await click(container.querySelector('.primary-button'))
    assert.equal(container.querySelector('.upload-zone'), null)
    assert.equal(container.querySelector('.connection-panel'), null)
    assert.ok(container.querySelector('.review-workspace'))
    const originalPlayer = video()
    assert.equal(container.querySelectorAll('video').length, 1)
    await click(rows()[1])
    assert.equal(video(), originalPlayer, 'Switching episodes must reuse the same video')
    assert.match(container.querySelector('.episode-description').textContent, /Другой эпизод/)
    await click(container.querySelector('.result-heading button'))
    assert.ok(container.querySelector('.upload-zone'))
    assert.equal(container.querySelector('video'), null)
  } finally {
    globalThis.fetch = savedFetch
    URL.createObjectURL = savedCreate
    URL.revokeObjectURL = savedRevoke
  }
})

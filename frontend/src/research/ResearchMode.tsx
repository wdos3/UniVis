import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, CheckCircle2, Download, FlaskConical } from 'lucide-react'
import { api } from '../api/client'
import { VisualInstructions } from '../components/VisualInstructions'
import type { AnalysisResult, DemoQuestion } from '../types'

type Condition = 'A' | 'B' | 'C'

function normalize(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9가-힣]/g, '')
}

export function ResearchMode({ result, questions, publicMode, onExit }: { result: AnalysisResult; questions: DemoQuestion[]; publicMode: boolean; onExit: () => void }) {
  const [participantId, setParticipantId] = useState('')
  const [condition, setCondition] = useState<Condition>('A')
  const [started, setStarted] = useState(false)
  const [startedAt, setStartedAt] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [confidence, setConfidence] = useState(3)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { window.scrollTo(0, 0) }, [started])
  const allAnswered = useMemo(() => questions.length > 0 && questions.every((q) => answers[q.id]?.trim()), [answers, questions])

  function begin() {
    setStartedAt(new Date().toISOString())
    setStarted(true)
  }

  async function submit() {
    const finishedAt = new Date()
    const expected = new Map(questions.map((question) => [question.id, question.expected_answer]))
    try {
      await api.saveResearch({
        participant_id: participantId,
        notice_id: result.id,
        condition,
        started_at: startedAt,
        finished_at: finishedAt.toISOString(),
        duration_seconds: Math.max(0, Math.round((finishedAt.getTime() - new Date(startedAt).getTime()) / 1000)),
        confidence,
        answers: questions.map((question) => ({
          question_id: question.id,
          answer: answers[question.id],
          correct: normalize(answers[question.id]).includes(normalize(expected.get(question.id) ?? '')) || normalize(expected.get(question.id) ?? '').includes(normalize(answers[question.id])),
        })),
      })
      setSaved(true)
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Could not save the result.') }
  }

  if (!started) return <main className="research-setup page-shell">
    <button className="text-button" onClick={onExit}><ArrowLeft size={16} />Back to workspace</button>
    <section className="setup-card">
      <div className="mode-icon"><FlaskConical /></div>
      <span className="eyebrow-text">Controlled presentation</span>
      <h1>Research Mode</h1>
      <p>Choose one condition. Participants will see only that presentation format.</p>
      <label>Participant ID<input value={participantId} onChange={(event) => setParticipantId(event.target.value)} placeholder="e.g. P-001" /></label>
      <fieldset><legend>Condition</legend><div className="condition-picker">
        {([['A', 'Translation', 'Faithful English baseline'], ['B', 'Simplified Text', 'Structured text only'], ['C', 'Visual Instructions', 'Icons and visual structure']] as const).map(([code, title, description]) => <label className={condition === code ? 'selected' : ''} key={code}><input type="radio" name="condition" value={code} checked={condition === code} onChange={() => setCondition(code)} /><strong>{code} — {title}</strong><span>{description}</span></label>)}
      </div></fieldset>
      <button className="primary-button" disabled={!participantId.trim() || questions.length === 0} onClick={begin}>Begin study task</button>
      {questions.length === 0 && <p className="inline-notice">Comprehension questions are available for synthetic demo notices.</p>}
    </section>
  </main>

  if (saved) return <main className="research-setup page-shell"><section className="setup-card success-state"><CheckCircle2 size={42} /><h1>Response recorded</h1><p>The study result was saved on this site's server.</p>{!publicMode && <a className="secondary-button" href="/api/research/results.csv" download><Download size={16} />Export Study Results CSV</a>}<button className="text-button centered" onClick={onExit}>Return to workspace</button></section></main>

  return <main className="research-session page-shell">
    <header className="session-header"><div><span>Participant {participantId}</span><strong>Condition {condition}</strong></div><span className="privacy-chip">Study responses are saved on the server</span></header>
    <section className="condition-output" aria-label={`Condition ${condition}`}>
      {condition === 'A' && <article className="reading-condition"><span className="condition-label">University notice · English translation</span><h1>{result.notice.title}</h1><div className="prose-output">{result.faithful_translation}</div></article>}
      {condition === 'B' && <article className="reading-condition"><span className="condition-label">University notice · Simplified English</span><h1>{result.notice.title}</h1><div className="prose-output simplified-output">{result.simplified_text}</div></article>}
      {condition === 'C' && <VisualInstructions result={result} compact />}
    </section>
    <section className="question-panel"><span className="eyebrow-text">Comprehension check</span><h2>Answer from the notice above</h2>
      {questions.map((question, index) => <label key={question.id}><span>{index + 1}. {question.prompt}</span><input value={answers[question.id] ?? ''} onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })} /></label>)}
      <fieldset className="confidence"><legend>How confident are you that you understood the notice?</legend><div>{[1, 2, 3, 4, 5].map((score) => <label key={score}><input type="radio" name="confidence" checked={confidence === score} onChange={() => setConfidence(score)} /><span>{score}</span></label>)}</div><div className="scale-labels"><span>Not confident</span><span>Very confident</span></div></fieldset>
      {error && <p className="error-message" role="alert">{error}</p>}
      <button className="primary-button" disabled={!allAnswered} onClick={submit}>Submit responses</button>
    </section>
  </main>
}

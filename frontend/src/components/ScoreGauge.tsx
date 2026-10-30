import { formatScore, scoreTone } from '../lib/format'

interface ScoreGaugeProps {
  score: number | null | undefined
  size?: 'small' | 'large'
  label?: string
}

export function ScoreGauge({ score, size = 'small', label = 'Security score' }: ScoreGaugeProps) {
  const normalized = score == null || !Number.isFinite(score) ? 0 : Math.max(0, Math.min(100, score))
  const tone = scoreTone(score)
  return (
    <div
      className={`score-gauge score-gauge--${size} score-gauge--${tone}`}
      style={{ '--score': `${normalized * 3.6}deg` } as React.CSSProperties}
      role="img"
      aria-label={`${label}: ${formatScore(score)}`}
    >
      <div className="score-gauge__inner">
        <strong>{formatScore(score)}</strong>
        {size === 'large' && <span>{label}</span>}
      </div>
    </div>
  )
}

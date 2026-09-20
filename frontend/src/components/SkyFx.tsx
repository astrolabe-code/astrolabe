import { useEffect, useState } from 'react'

interface Star {
  cls: string
  left: number
  top: number
  dur: number
  delay: number
}

/** 与旧站 base.js 同规则:移动端 6 颗,浅色 20 颗淡星,深色 42 颗亮星 */
function makeStars(): Star[] {
  const dark = document.documentElement.getAttribute('data-theme') === 'dark'
  const coarse = window.matchMedia?.('(pointer: coarse)').matches || window.innerWidth < 768
  const count = coarse ? 6 : dark ? 42 : 20
  const out: Star[] = []
  for (let i = 0; i < count; i++) {
    const r = Math.random()
    out.push({
      cls: r > 0.78 ? 'big' : r < 0.22 ? 'dim' : '',
      left: +(Math.random() * 96 + 2).toFixed(1),
      // 星星集中在顶部天空区(深色可延伸更低),避开中部内容
      top: +(Math.random() * (dark ? 46 : 30) + 1).toFixed(1),
      dur: +(2.4 + Math.random() * 2.8).toFixed(1),
      delay: +(Math.random() * 3).toFixed(1),
    })
  }
  return out
}

export default function SkyFx() {
  const [stars, setStars] = useState<Star[]>(() => makeStars())

  useEffect(() => {
    const onTheme = () => setStars(makeStars())
    document.addEventListener('themechange', onTheme)
    return () => document.removeEventListener('themechange', onTheme)
  }, [])

  return (
    <div className="skyfx" aria-hidden="true">
      <div className="beam" />
      <div className="vignette" />
      <div className="stars">
        {stars.map((s, i) => (
          <i
            key={i}
            className={s.cls}
            style={{
              left: `${s.left}%`,
              top: `${s.top}%`,
              animationDuration: `${s.dur}s`,
              animationDelay: `${s.delay}s`,
            }}
          />
        ))}
      </div>
      <div className="horizon" />
      <div className="iceglow" />
      <div className="underlight" />
      <div className="dust">
        <i style={{ left: '12%', animationDuration: '10s', animationDelay: '0s' }} />
        <i style={{ left: '30%', animationDuration: '11s', animationDelay: '3s' }} />
        <i style={{ left: '52%', animationDuration: '9s', animationDelay: '6s' }} />
        <i style={{ left: '70%', animationDuration: '10.5s', animationDelay: '2s' }} />
        <i style={{ left: '88%', animationDuration: '9.5s', animationDelay: '5s' }} />
      </div>
      <div className="morning-star" />
    </div>
  )
}

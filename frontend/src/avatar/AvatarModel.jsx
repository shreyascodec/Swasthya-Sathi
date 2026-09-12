import { useEffect, useRef, useCallback } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF, useAnimations } from '@react-three/drei'
import * as THREE from 'three'
import { MeshoptDecoder } from 'three-stdlib'
import { NOD_KEYWORDS, SHAKE_KEYWORDS } from './expressions'

// Served by the backend's dedicated no-store avatar route (server/main.py),
// NOT the SPA static mount — so a browser 304 can't hand three.js an empty body.
const MAIN_ASSET  = '/avatar/characters/Brenin_Avatar/Brenin.gltf'
const ANIMS_ASSET = '/avatar/characters/Brenin_Anims/Brenin_Anims.glb'

// ─── Animation pools ──────────────────────────────────────────────────────────
const IDLE_ANIMS    = ['coreIdle0', 'coreIdle9', 'coreIdle13', 'coreIdle14',
                       'coreIdle0_NH', 'coreIdle9_NH', 'coreIdle13_NH', 'coreIdle14_NH']
const TALKING_ANIMS = ['baseTalking1', 'baseTalking2', 'baseTalking2A', 'baseTalking4',
                       'baseTalking5A', 'baseTalking5B', 'baseTalking6', 'baseTalking6A',
                       'baseTalking6B', 'baseTalking8']
const LISTENING_ANIMS = ['coreListeningNodA', 'coreListeningNodB', 'coreListeningNodC',
                          'coreListeningNodD', 'coreListeningNodE', 'coreListeningNodF',
                          'coreListeningNodG', 'coreListeningNodMedium', 'coreListeningNodSmall2',
                          'ListeningNodSmall', 'ListeningNodSmall2', 'ListeningNodMedium', 'ListeningNodSlow']
const NOD_ANIMS   = ['noddingSmall', 'noddingMedium', 'coreNoddingSmall', 'MCnoddingSlow']
const SHAKE_ANIMS = ['MCshakeAverage', 'MCshakeFast', 'MCshakeSlow']
const TILT_ANIMS  = ['tiltLeftMedium1', 'tiltLeftMedium2', 'tiltRightMedium1', 'tiltRightMedium2',
                     'tiltUpMedium2', 'tiltDownMedium1', 'tiltLeftTurnMedium1', 'tiltRightTurnMedium1',
                     'translateLeftSmall', 'translateRightSmall', 'translateUpSmall']

// How long between random idle tilts (seconds)
const TILT_INTERVAL_MIN = 8
const TILT_INTERVAL_MAX = 18

// ─── Blink timing ─────────────────────────────────────────────────────────────
const BLINK_GAP_MIN      = 2.0
const BLINK_GAP_MAX      = 7.0
const BLINK_CLOSE        = 0.055
const BLINK_HOLD_MIN     = 0.020
const BLINK_HOLD_MAX     = 0.055
const BLINK_OPEN         = 0.120
const SLOW_BLINK_CHANCE  = 0.10
const SLOW_BLINK_FACTOR  = 2.5
const DOUBLE_BLINK_CHANCE = 0.05

const smoothstep = t => t * t * (3 - 2 * t)
const clamp01    = v => Math.max(0, Math.min(1, v))
const pick       = arr => arr[Math.floor(Math.random() * arr.length)]

const meshoptDecoder = MeshoptDecoder()
function loaderSetup(loader) { loader.setMeshoptDecoder(meshoptDecoder) }

// ─── Lip sync visemes ─────────────────────────────────────────────────────────
const VISEME_SHAPES = {
  sil: { stickyLips: 0.40, lipsTopThin: 0.03 },
  PP:  { stickyLips: 0.70, mouthPressLeft: 0.30, mouthPressRight: 0.38 },
  FF:  { lipsBottomDown: 0.14, lipsTopUp: 0.12, jawOpen: 0.03, stickyLips: 0.05 },
  TH:  { jawOpen: 0.04, lipsJawDown: 0.06, stickyLips: 0.05 },
  DD:  { jawOpen: 0.05, lipsJawDown: 0.10, stickyLips: 0.10 },
  kk:  { jawOpen: 0.06, lipsJawDown: 0.14, mouthStretchLeft: 0.07, mouthStretchRight: 0.07 },
  CH:  { jawOpen: 0.04, lipsNarrow: 0.20, lipsJawDown: 0.08, lipsTurn: 0.10 },
  SS:  { jawOpen: 0.03, mouthSmileLeft: 0.08, mouthSmileRight: 0.08, lipsTopThin: 0.04 },
  nn:  { stickyLips: 0.50, jawOpen: 0.01 },
  RR:  { jawOpen: 0.05, lipsJawDown: 0.12, lipsNarrow: 0.10, stickyLips: 0.05 },
  aa:  { jawOpen: 0.08, lipsJawDown: 0.24, lipsBottomDown: 0.36, lipsTopUp: 0.55, lipsTopQuarterUp: 0.26, lipsBottomThin: 0.14 },
  E:   { jawOpen: 0.06, lipsJawDown: 0.16, lipsBottomDown: 0.20, lipsTopUp: 0.28, mouthSmileLeft: 0.16, mouthSmileRight: 0.16 },
  I:   { jawOpen: 0.03, lipsJawDown: 0.08, lipsTopUp: 0.18, mouthSmileLeft: 0.24, mouthSmileRight: 0.24, cheekSquintLeft: 0.06, cheekSquintRight: 0.06 },
  O:   { jawOpen: 0.07, lipsJawDown: 0.20, lipsBottomDown: 0.24, lipsTopUp: 0.30, lipsNarrow: 0.18, lipsTurn: 0.10 },
  U:   { jawOpen: 0.03, lipsJawDown: 0.09, lipsNarrow: 0.36, lipsTurn: 0.22, mouthFunnel: 0.014 },
}

// ─── Facial expressions ───────────────────────────────────────────────────────
const EXPRESSION_SHAPES = {
  neutral:   {},
  happy:     { mouthSmileLeft: 0.65, mouthSmileRight: 0.65, cheekSquintLeft: 0.35, cheekSquintRight: 0.35, browInnerUp: 0.15 },
  sad:       { mouthFrownLeft: 0.55, mouthFrownRight: 0.55, browDownLeft: 0.25, browDownRight: 0.25, browInnerUp: 0.55 },
  surprised: { eyeWideLeft: 0.85, eyeWideRight: 0.85, browOuterUpLeft: 0.75, browOuterUpRight: 0.75, browInnerUp: 0.70, jawOpen: 0.04 },
  angry:     { browDownLeft: 0.75, browDownRight: 0.75, eyeSquintLeft: 0.30, eyeSquintRight: 0.30, noseSneerLeft: 0.28, noseSneerRight: 0.28, mouthFrownLeft: 0.25, mouthFrownRight: 0.25 },
  thinking:  { browDownLeft: 0.45, browInnerUp: 0.35, mouthDimpleLeft: 0.22, mouthPressLeft: 0.12 },
  laugh:     { mouthSmileLeft: 0.90, mouthSmileRight: 0.90, cheekSquintLeft: 0.70, cheekSquintRight: 0.70, eyeSquintLeft: 0.50, eyeSquintRight: 0.50, browInnerUp: 0.30, jawOpen: 0.05, lipsTopUp: 0.20, lipsBottomDown: 0.12 },
  excited:   { eyeWideLeft: 0.70, eyeWideRight: 0.70, browOuterUpLeft: 0.65, browOuterUpRight: 0.65, browInnerUp: 0.65, mouthSmileLeft: 0.60, mouthSmileRight: 0.60, cheekSquintLeft: 0.30, cheekSquintRight: 0.30 },
}

const ALL_LIP_KEYS   = [...new Set(Object.values(VISEME_SHAPES).flatMap(s => Object.keys(s)))]
const ALL_EXPR_KEYS  = [...new Set(Object.values(EXPRESSION_SHAPES).flatMap(s => Object.keys(s)))]
const ALL_BLEND_KEYS = [...new Set([...ALL_LIP_KEYS, ...ALL_EXPR_KEYS])]

const LIP_TRANSITION  = 0.055
const LIP_RETURN      = 0.080
const EXPR_TRANSITION = 0.300
const EXPR_RETURN     = 0.400

function applyMaterialFixes(scene) {
  scene.traverse((node) => {
    if (!node.isMesh && !node.isSkinnedMesh) return
    const mats = Array.isArray(node.material) ? node.material : [node.material]
    mats.forEach((mat) => {
      if (!mat) return
      if (mat.name === 'Std_Eyelash') { mat.alphaTest = 0.1; mat.transparent = false; mat.needsUpdate = true }
      if (mat.map)         mat.map.colorSpace        = THREE.SRGBColorSpace
      if (mat.emissiveMap) mat.emissiveMap.colorSpace = THREE.SRGBColorSpace
    })
  })
}

export function AvatarModel({ speaking, listening, amplitude, visemeRef, expressionRef }) {
  const { scene }      = useGLTF(MAIN_ASSET,  false, false, loaderSetup)
  const { animations } = useGLTF(ANIMS_ASSET, false, false, loaderSetup)

  const groupRef      = useRef()
  const fixAppliedRef = useRef(false)

  // Mirror props to refs for use inside useFrame
  const amplitudeRef  = useRef(0)
  const speakingRef   = useRef(false)
  const listeningRef  = useRef(false)
  amplitudeRef.current = amplitude
  speakingRef.current  = speaking
  listeningRef.current = listening

  // Morph state
  const lipStateRef   = useRef({})
  const prevVisemeRef = useRef('sil')
  const exprStateRef  = useRef({})
  const prevExprRef   = useRef('neutral')

  // Animation layer refs
  const baseActionRef  = useRef(null)   // current looping base (idle / talking / listening)
  const oneShotRef     = useRef(null)   // nod / shake — plays once then returns to base
  const tiltTimerRef   = useRef(TILT_INTERVAL_MIN + Math.random() * (TILT_INTERVAL_MAX - TILT_INTERVAL_MIN))

  const { actions } = useAnimations(animations, groupRef)

  useEffect(() => {
    if (scene && !fixAppliedRef.current) { applyMaterialFixes(scene); fixAppliedRef.current = true }
  }, [scene])

  // ── Helpers ──────────────────────────────────────────────────────────────────
  const playBase = useCallback((name, fade = 0.5) => {
    const next = actions[name]
    if (!next) return
    if (baseActionRef.current?.getClip().name === name) return
    baseActionRef.current?.fadeOut(fade)
    next.reset().setLoop(THREE.LoopRepeat, Infinity).fadeIn(fade).play()
    baseActionRef.current = next
  }, [actions])

  const playOneShot = useCallback((name, fade = 0.3) => {
    const next = actions[name]
    if (!next) return
    // Interrupt any previous one-shot
    if (oneShotRef.current && oneShotRef.current !== next) {
      oneShotRef.current.fadeOut(0.2)
    }
    oneShotRef.current = next
    next.reset().setLoop(THREE.LoopOnce, 1).clampWhenFinished = true
    next.fadeIn(fade).play()

    // Return to base after clip ends
    const dur = next.getClip().duration * 1000
    setTimeout(() => {
      if (oneShotRef.current === next) {
        next.fadeOut(0.4)
        oneShotRef.current = null
      }
    }, dur)
  }, [actions])

  const pickPool = useCallback((pool) => {
    const available = pool.filter(n => actions[n])
    return available.length ? pick(available) : null
  }, [actions])

  // ── Initial idle ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!Object.keys(actions).length) return
    const name = pickPool(IDLE_ANIMS)
    if (name) playBase(name, 0)
  }, [actions])

  // ── Base animation switches on speaking / listening ───────────────────────────
  useEffect(() => {
    if (!Object.keys(actions).length) return
    let pool
    if (speaking)   pool = TALKING_ANIMS
    else if (listening) pool = LISTENING_ANIMS
    else            pool = IDLE_ANIMS
    const name = pickPool(pool) ?? pickPool(IDLE_ANIMS)
    if (name) playBase(name)
  }, [speaking, listening, actions])

  // ── Text-driven one-shot gestures (exposed via ref so App can trigger) ────────
  // Called from App when speak() is called with the text
  useEffect(() => {
    if (!expressionRef) return
    // Expose trigger fn on the ref so App.jsx can call it after text analysis
    expressionRef._triggerGesture = (text) => {
      if (!Object.keys(actions).length) return
      if (NOD_KEYWORDS.test(text)) {
        const name = pickPool(NOD_ANIMS)
        if (name) playOneShot(name)
      } else if (SHAKE_KEYWORDS.test(text)) {
        const name = pickPool(SHAKE_ANIMS)
        if (name) playOneShot(name)
      }
    }
  }, [actions, expressionRef, playOneShot, pickPool])

  // ── Blink state ───────────────────────────────────────────────────────────────
  const blinkRef = useRef({
    phase: 'wait', countdown: 1.0 + Math.random() * 2.0,
    t: 0, closeTime: BLINK_CLOSE, holdTime: BLINK_HOLD_MIN,
    openTime: BLINK_OPEN, doublePending: false,
  })

  // ── useFrame ──────────────────────────────────────────────────────────────────
  useFrame((_, delta) => {
    if (!groupRef.current) return
    const amp = amplitudeRef.current
    const spk = speakingRef.current
    const vsm = visemeRef?.current ?? 'sil'
    const exp = expressionRef?.current ?? 'neutral'

    // ── Random idle tilt ───────────────────────────────────────────────────────
    if (!spk && !listeningRef.current) {
      tiltTimerRef.current -= delta
      if (tiltTimerRef.current <= 0) {
        const name = pickPool(TILT_ANIMS)
        if (name) playOneShot(name, 0.2)
        tiltTimerRef.current = TILT_INTERVAL_MIN + Math.random() * (TILT_INTERVAL_MAX - TILT_INTERVAL_MIN)
      }
    }

    // ── Lip sync transition ────────────────────────────────────────────────────
    if (vsm !== prevVisemeRef.current) {
      const targets = VISEME_SHAPES[vsm] ?? VISEME_SHAPES.sil
      const state   = lipStateRef.current
      const dur     = spk ? LIP_TRANSITION : LIP_RETURN
      for (const key of ALL_LIP_KEYS) {
        const fromVal = state[key]?.current ?? 0
        state[key] = { from: fromVal, to: targets[key] ?? 0, elapsed: 0, duration: dur, current: fromVal }
      }
      prevVisemeRef.current = vsm
    }

    // ── Expression transition ──────────────────────────────────────────────────
    if (exp !== prevExprRef.current) {
      const targets = EXPRESSION_SHAPES[exp] ?? EXPRESSION_SHAPES.neutral
      const state   = exprStateRef.current
      const dur     = exp === 'neutral' ? EXPR_RETURN : EXPR_TRANSITION
      for (const key of ALL_EXPR_KEYS) {
        const fromVal = state[key]?.current ?? 0
        state[key] = { from: fromVal, to: targets[key] ?? 0, elapsed: 0, duration: dur, current: fromVal }
      }
      prevExprRef.current = exp
    }

    // ── Advance morph targets ──────────────────────────────────────────────────
    groupRef.current.traverse((node) => {
      if (!node.isSkinnedMesh || !node.morphTargetDictionary) return
      const dict = node.morphTargetDictionary
      const infl = node.morphTargetInfluences

      for (const key of ALL_BLEND_KEYS) {
        const idx = dict[key]
        if (idx === undefined) continue
        let lipVal = 0
        const ls = lipStateRef.current[key]
        if (ls) {
          ls.elapsed = Math.min(ls.elapsed + delta, ls.duration)
          ls.current = ls.from + (ls.to - ls.from) * smoothstep(ls.elapsed / ls.duration)
          lipVal = ls.current
        }
        let exprVal = 0
        const es = exprStateRef.current[key]
        if (es) {
          es.elapsed = Math.min(es.elapsed + delta, es.duration)
          es.current = es.from + (es.to - es.from) * smoothstep(es.elapsed / es.duration)
          exprVal = es.current
        }
        let v = lipVal + exprVal
        if (key === 'jawOpen') {
          // Let loudness modulate the jaw: at 0.03 coupling under a 0.08 cap the
          // vowel viseme already sat at the ceiling, so amplitude did nothing.
          // Bump both so loud syllables open visibly; still bounded (never gapes).
          if (spk) v = lipVal + amp * 0.06 + exprVal
          v = Math.min(v, 0.14)
        }
        infl[idx] = clamp01(v)
      }

      // ── Blink ──────────────────────────────────────────────────────────────
      const blinkL = dict['eyeBlinkLeft']
      const blinkR = dict['eyeBlinkRight']
      if (blinkL === undefined || blinkR === undefined) return

      const wideVal = clamp01(exprStateRef.current['eyeWideLeft']?.current ?? 0)
      const blink   = blinkRef.current

      if (blink.phase === 'wait') {
        blink.countdown -= delta
        if (blink.countdown <= 0) {
          const slow = Math.random() < SLOW_BLINK_CHANCE
          const sf   = slow ? SLOW_BLINK_FACTOR : 1.0
          blink.closeTime     = BLINK_CLOSE * sf
          blink.holdTime      = BLINK_HOLD_MIN + Math.random() * (BLINK_HOLD_MAX - BLINK_HOLD_MIN)
          blink.openTime      = BLINK_OPEN * sf
          blink.doublePending = Math.random() < DOUBLE_BLINK_CHANCE
          blink.t = 0; blink.phase = 'closing'
        }
      } else if (blink.phase === 'closing') {
        blink.t = Math.min(blink.t + delta / blink.closeTime, 1)
        const v = (blink.t * blink.t) * (1 - wideVal)
        infl[blinkL] = v; infl[blinkR] = v
        if (blink.t >= 1) { blink.phase = 'hold'; blink.t = 0 }
      } else if (blink.phase === 'hold') {
        blink.t += delta
        if (blink.t >= blink.holdTime) { blink.phase = 'opening'; blink.t = 0 }
      } else if (blink.phase === 'opening') {
        blink.t = Math.min(blink.t + delta / blink.openTime, 1)
        const tInv = 1 - blink.t
        const v    = (tInv * tInv) * (1 - wideVal)
        infl[blinkL] = v; infl[blinkR] = v
        if (blink.t >= 1) {
          if (blink.doublePending) {
            blink.doublePending = false
            blink.countdown = 0.06 + Math.random() * 0.04
            blink.phase = 'wait'
          } else {
            blink.countdown = BLINK_GAP_MIN + Math.random() * (BLINK_GAP_MAX - BLINK_GAP_MIN)
            blink.phase = 'wait'
            infl[blinkL] = 0; infl[blinkR] = 0
          }
        }
      }
    })
  })

  return (
    <group ref={groupRef}>
      <primitive object={scene} />
    </group>
  )
}

useGLTF.preload(MAIN_ASSET,  false, false, loaderSetup)
useGLTF.preload(ANIMS_ASSET, false, false, loaderSetup)

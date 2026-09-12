import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { AvatarModel } from './AvatarModel'

// OFFLINE kiosk note: the original used drei's <Environment preset="studio"/>,
// which fetches an HDR from a CDN and fails with no internet. We drop the IBL
// and compensate with brighter key/fill/rim + a soft ambient. Skin is a touch
// flatter than with IBL, but it renders fully offline.
function Lights() {
  return (
    <>
      <ambientLight intensity={0.55} color="#eef4ff" />
      {/* Key light — soft warm from upper-right front */}
      <directionalLight position={[1.2, 2.5, 2.0]} intensity={1.1} color="#fff8f0" />
      {/* Fill — cool from left to separate from key */}
      <directionalLight position={[-1.5, 1.0, 1.5]} intensity={0.5} color="#c8deff" />
      {/* Rim — behind-right to lift hair and shoulders */}
      <directionalLight position={[1.0, 1.5, -2.0]} intensity={0.6} color="#fff5e8" />
    </>
  )
}

export function AvatarScene({ speaking, listening, amplitude, visemeRef, expressionRef }) {
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* Brenin backdrop: soft neutral studio gradient */}
      <div style={{
        position: 'absolute', inset: 0,
        background: 'radial-gradient(ellipse at 50% 40%, #c8d8e8 0%, #8aa8bf 35%, #4a7090 65%, #263d52 100%)',
        zIndex: 0,
      }} />
      <Canvas
        shadows={false}
        camera={{ position: [0, 1.35, 2.2], fov: 28, near: 0.05, far: 100 }}
        style={{ position: 'relative', zIndex: 1, background: 'transparent' }}
        gl={{
          antialias: true,
          alpha: true,
          outputColorSpace: THREE.SRGBColorSpace,
          toneMapping: THREE.ACESFilmicToneMapping,
          toneMappingExposure: 0.85,
        }}
        onCreated={({ gl }) => {
          gl.useLegacyLights = false
          gl.setClearColor(0x000000, 0)
        }}
      >
        <Lights />
        <Suspense fallback={null}>
          <AvatarModel speaking={speaking} listening={listening} amplitude={amplitude} visemeRef={visemeRef} expressionRef={expressionRef} />
        </Suspense>
        <OrbitControls target={[0, 1.35, 0]} minDistance={0.5} maxDistance={4} enablePan={false} enableZoom={false} />
      </Canvas>
    </div>
  )
}

// Contains any 3D-avatar failure (WebGL unavailable, asset load error, GLTF
// parse failure) so it NEVER blanks the kiosk. The question is still spoken —
// useAvatarTTS plays audio independently of the canvas — so a broken avatar
// degrades to voice-only, not a dead screen.

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props { children: ReactNode; fallback?: ReactNode }
interface State { failed: boolean }

export class AvatarBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log for support; do not rethrow — the rest of the intake screen keeps working.
    console.error("[avatar] render failed, falling back to voice-only:", error, info);
  }

  render() {
    if (this.state.failed) {
      return (
        this.props.fallback ?? (
          <div
            style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              height: "100%", color: "#5b7085", fontSize: 14, textAlign: "center",
              padding: 16,
              background: "radial-gradient(ellipse at 50% 40%, #c8d8e8 0%, #8aa8bf 45%, #4a7090 100%)",
            }}
          >
            🔊 Playing the question aloud…
          </div>
        )
      );
    }
    return this.props.children;
  }
}

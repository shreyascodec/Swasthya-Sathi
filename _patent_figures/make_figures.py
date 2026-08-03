"""Generate patent line-diagrams as PNG: 5 figures x {labeled, unlabeled}."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon
from pathlib import Path

OUT = Path(__file__).resolve().parent
LW = 1.6
FS = 8.5


def new_ax(w=12, h=7):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, text, labeled, fs=FS, dashed=False, fc="white"):
    ls = (0, (5, 3)) if dashed else "solid"
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.4,rounding_size=1.2",
            linewidth=LW,
            edgecolor="black",
            facecolor=fc,
            linestyle=ls,
        )
    )
    if labeled and text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, wrap=True)


def diamond(ax, cx, cy, w, h, text, labeled, fs=FS - 0.5):
    pts = [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)]
    ax.add_patch(Polygon(pts, closed=True, linewidth=LW, edgecolor="black", facecolor="white"))
    if labeled and text:
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fs)


def arrow(ax, x1, y1, x2, y2, dashed=False):
    ls = (0, (4, 3)) if dashed else "solid"
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=LW,
            color="black",
            linestyle=ls,
            shrinkA=2,
            shrinkB=2,
        )
    )


def label(ax, x, y, text, labeled, fs=FS, style="italic", ha="center"):
    if labeled:
        ax.text(x, y, text, ha=ha, va="center", fontsize=fs, style=style)


def save(fig, name):
    fig.savefig(OUT / name, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig1(labeled):
    fig, ax = new_ax()
    box(ax, 38, 42, 24, 16, "COMPUTE UNIT\n(single ~8 GB GPU box)", labeled, fs=FS)
    box(ax, 6, 68, 22, 12, "Camera /\nDocument scanner", labeled)
    box(ax, 6, 20, 22, 12, "Microphone", labeled)
    box(ax, 72, 68, 22, 12, "Display", labeled)
    box(ax, 72, 20, 22, 12, "Speaker", labeled)
    box(ax, 38, 12, 24, 12, "Local encrypted\nstorage", labeled)
    arrow(ax, 28, 72, 40, 56)
    arrow(ax, 28, 26, 40, 44)
    arrow(ax, 62, 52, 72, 72)
    arrow(ax, 62, 48, 72, 26)
    arrow(ax, 50, 42, 50, 24)
    arrow(ax, 50, 24, 50, 42)
    box(ax, 40, 82, 20, 10, "INTERNET", labeled, dashed=True)
    ax.plot([42, 58], [91, 83], color="black", lw=2)
    ax.plot([42, 58], [83, 91], color="black", lw=2)
    label(ax, 68, 87, "no network connection (offline by design)", labeled, ha="left")
    if labeled:
        ax.text(50, 97, "FIG. 1", ha="center", fontsize=11, weight="bold")
    save(fig, f"fig1_system_{'labeled' if labeled else 'clean'}.png")


def fig2(labeled):
    fig, ax = new_ax(14, 6.5)
    names = [
        "1\nIntake &\npreprocess",
        "2\nText\nextraction",
        "3\nImage\ntyping",
        "4\nFaithful\nstructuring",
        "5\nInterpret\n(separate\nfiling)",
        "6\nQuestion\nselection",
        "7\nVoice",
        "8\nAnswer\ncapture",
        "9\nSeal &\nrecord",
    ]
    n = len(names)
    w = 9.2
    gap = (100 - n * w) / (n + 1)
    y = 52
    h = 20
    xs = []
    for i, nm in enumerate(names):
        x = gap + i * (w + gap)
        xs.append(x)
        box(ax, x, y, w, h, nm, labeled, fs=6.8, dashed=(i == 4))
        if i > 0:
            arrow(ax, xs[i - 1] + w, y + h / 2, x, y + h / 2)
    box(
        ax,
        xs[0],
        20,
        xs[-1] + w - xs[0],
        9,
        "SESSION RECORD (single object; stages share only this)",
        labeled,
        fs=7.5,
    )
    for x in xs:
        arrow(ax, x + w / 2, y, x + w / 2, 29, dashed=True)
    label(ax, xs[0] + w / 2, 84, "HOLD:\nre-scan if\npoor quality", labeled, fs=6.8, style="normal")
    arrow(ax, xs[0] + w / 2, 79, xs[0] + w / 2, y + h)
    label(ax, xs[6] + w / 2, 84, "HOLD:\nanswer before\nsealing", labeled, fs=6.8, style="normal")
    arrow(ax, xs[6] + w / 2, 79, xs[6] + w / 2, y + h)
    if labeled:
        ax.text(50, 98, "FIG. 2", ha="center", fontsize=11, weight="bold")
    save(fig, f"fig2_pipeline_{'labeled' if labeled else 'clean'}.png")


def fig3(labeled):
    fig, ax = new_ax()
    for i, r in enumerate(
        ["OCR engine", "Language model", "Voice (TTS)", "Speech-to-text", "Image tagger"]
    ):
        yy = 78 - i * 13
        box(ax, 4, yy, 20, 9, r, labeled, fs=7)
        arrow(ax, 24, yy + 4.5, 38, 50)
    box(
        ax,
        38,
        40,
        24,
        22,
        "MODEL MANAGER\n\nrole -> engine\n+ device + precision\nenforce memory ceiling",
        labeled,
        fs=7.5,
    )
    box(ax, 38, 74, 24, 10, "Config profile\n(hardware, limits)", labeled, dashed=True, fs=7)
    arrow(ax, 50, 74, 50, 62)
    box(ax, 72, 30, 24, 46, "", labeled)
    box(ax, 74, 66, 20, 7, "PINNED (small,\nalways resident)", labeled, fs=6.8)
    box(ax, 74, 56, 20, 7, "PINNED", labeled, fs=6.8)
    box(ax, 74, 34, 20, 18, "ONE HEAVY MODEL\n(swapped in/out)", labeled, fs=6.8)
    label(ax, 84, 79, "GPU memory (ceiling)", labeled, fs=7, style="normal")
    arrow(ax, 62, 50, 72, 52)
    box(
        ax,
        30,
        8,
        40,
        9,
        "STARTUP WARM-UP: load + one throwaway inference each",
        labeled,
        dashed=True,
        fs=7,
    )
    arrow(ax, 50, 17, 50, 40)
    if labeled:
        ax.text(50, 97, "FIG. 3", ha="center", fontsize=11, weight="bold")
    save(fig, f"fig3_modelmgr_{'labeled' if labeled else 'clean'}.png")


def fig4(labeled):
    """Clean top-down intake routing — no crossing arrows."""
    fig, ax = new_ax(12, 11)
    # Start
    box(ax, 40, 92, 20, 5.5, "Input received", labeled, fs=7.5)
    arrow(ax, 50, 92, 50, 88.5)
    diamond(ax, 50, 84, 20, 8, "PDF or\nphoto?", labeled, fs=7)

    # Left: PDF
    arrow(ax, 40, 84, 20, 84)
    label(ax, 30, 87, "PDF", labeled, fs=7, style="normal")
    diamond(ax, 20, 72, 20, 9, "text layer\npresent?", labeled, fs=7)
    arrow(ax, 20, 80, 20, 76.5)

    arrow(ax, 10, 72, 10, 64)
    label(ax, 6, 68, "yes", labeled, fs=6.5, style="normal")
    box(ax, 1, 56, 18, 8, "Use text layer\n(skip OCR)", labeled, fs=7)
    arrow(ax, 10, 56, 10, 48)
    box(ax, 1, 40, 18, 8, "-> Faithful\nstructuring", labeled, fs=7)

    # PDF no-text joins prepare
    arrow(ax, 30, 72, 42, 64)
    label(ax, 38, 70, "no", labeled, fs=6.5, style="normal")

    # Right: photo joins prepare
    arrow(ax, 60, 84, 58, 68)
    label(ax, 66, 78, "photo", labeled, fs=7, style="normal")

    # Shared prepare + quality
    box(ax, 38, 58, 36, 8, "Prepare page\n(render / normalise, deskew, denoise)", labeled, fs=6.8)
    arrow(ax, 56, 58, 56, 52)
    diamond(ax, 56, 46, 18, 8, "quality\nok?", labeled, fs=7)

    # Re-scan loop (right, then back up to Input)
    arrow(ax, 65, 46, 84, 46)
    label(ax, 74, 49, "no", labeled, fs=6.5, style="normal")
    box(ax, 78, 42, 18, 8, "RE-SCAN\n(operator)", labeled, fs=7)
    # loop back along right edge to input
    arrow(ax, 87, 50, 87, 94.5)
    arrow(ax, 87, 94.5, 60, 94.5)
    label(ax, 90, 72, "retry", labeled, fs=6.5, style="normal", ha="left")

    arrow(ax, 56, 42, 56, 36)
    label(ax, 60, 39, "yes", labeled, fs=6.5, style="normal")
    diamond(ax, 56, 30, 24, 9, "mostly white\n(document)?", labeled, fs=6.5)

    arrow(ax, 44, 30, 22, 30)
    label(ax, 33, 33, "no (photo)", labeled, fs=6.5, style="normal")
    box(ax, 4, 26, 20, 8, "-> Image typing", labeled, fs=7)

    arrow(ax, 56, 25.5, 56, 18)
    label(ax, 62, 22, "document", labeled, fs=6.5, style="normal")
    box(ax, 44, 10, 24, 8, "-> OCR (Stage 2)", labeled, fs=7)

    if labeled:
        ax.text(50, 99.5, "FIG. 4", ha="center", fontsize=11, weight="bold")
    save(fig, f"fig4_intake_{'labeled' if labeled else 'clean'}.png")


def fig5(labeled):
    """Build-time GPL phonemizer vs shipped Apache voice — data-only crossing."""
    fig, ax = new_ax(13, 8)
    ax.plot([50, 50], [5, 88], color="black", lw=2, linestyle=(0, (6, 4)))
    label(
        ax,
        25,
        94,
        "BUILD PHASE  (developer machine — copyleft tool allowed)",
        labeled,
        fs=7.5,
        style="normal",
    )
    label(
        ax,
        75,
        94,
        "SHIPPED KIOSK  (no copyleft code present)",
        labeled,
        fs=7.5,
        style="normal",
    )

    # Build column (left)
    box(
        ax,
        6,
        72,
        36,
        12,
        "Closed content set:\napproved question templates +\nanalytes + units + number range",
        labeled,
        fs=7,
    )
    arrow(ax, 24, 72, 24, 64)
    box(ax, 8, 52, 32, 12, "GPL PHONEMIZER\n(espeak-ng — build-time only)", labeled, fs=7)
    arrow(ax, 24, 52, 24, 42)
    box(ax, 8, 28, 32, 14, "PHONEME TABLE\n(plain data file)", labeled, fs=7.5)

    # Data crosses boundary only
    arrow(ax, 40, 35, 56, 35)
    label(ax, 48, 39, "data only", labeled, fs=7, style="normal")

    # Kiosk column (right) — top to bottom, no crossings
    box(ax, 58, 72, 36, 12, "Patient value\n(e.g. 168 mg/dL)", labeled, fs=7)
    arrow(ax, 76, 72, 76, 64)
    box(ax, 58, 50, 36, 14, "ASSEMBLE PHONEMES\n(template + value pieces\nfrom shipped table)", labeled, fs=7)
    box(ax, 58, 28, 16, 14, "Phoneme table\n(shipped)", labeled, fs=7)
    arrow(ax, 66, 42, 66, 50)  # table up into assemble
    arrow(ax, 76, 50, 76, 22)
    box(ax, 58, 8, 36, 14, "NEURAL VOICE MODEL\n(Apache-2.0) -> speaker", labeled, fs=7)

    if labeled:
        ax.text(50, 99, "FIG. 5", ha="center", fontsize=11, weight="bold")
    save(fig, f"fig5_voice_precompute_{'labeled' if labeled else 'clean'}.png")


if __name__ == "__main__":
    for fn in (fig1, fig2, fig3, fig4, fig5):
        fn(True)
        fn(False)
    print("wrote:", sorted(p.name for p in OUT.glob("fig*.png")))

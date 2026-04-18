"""TAG Capital visual identity: palette and matplotlib rcParams helper.

Every hex code used by the sentiment tracker is declared here and
imported elsewhere. Do not hardcode hex values in other modules.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# TAG Capital palette (locked — see spec)
# ---------------------------------------------------------------------------

LONG_NAVY = "#0A2540"       # Pop Mart (long position)
SHORT_GOLD = "#B8860B"      # Funko (short position)

BACKGROUND_WHITE = "#FFFFFF"
TEXT_DARK = "#1A1A1A"
TEXT_MUTED = "#64748B"

HIGHLIGHT_IVORY = "#F5F1E8"
LONG_FILL_PALE = "#F0F4F8"

BRAND_COLOR = {
    "popmart": LONG_NAVY,
    "funko": SHORT_GOLD,
}

BRAND_LEGEND_LABEL = {
    "popmart": "Pop Mart (long)",
    "funko": "Funko (short)",
}

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

PRIMARY_FONT_STACK = ["Arial", "DejaVu Sans", "sans-serif"]


def _pick_available_font() -> str:
    """Return the first font in the stack that matplotlib can locate.

    Falls back silently to ``DejaVu Sans`` (shipped with matplotlib) if
    Arial isn't installed — per the spec, no warning.
    """
    try:
        from matplotlib import font_manager
    except ImportError:
        return "DejaVu Sans"

    available = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in PRIMARY_FONT_STACK:
        if candidate in available:
            return candidate
    return "DejaVu Sans"


def get_matplotlib_rc() -> dict[str, Any]:
    """Return a dict of matplotlib rcParams that implements the house style.

    Apply globally with ``matplotlib.rcParams.update(get_matplotlib_rc())``
    before drawing.
    """
    font = _pick_available_font()
    return {
        "figure.facecolor": BACKGROUND_WHITE,
        "axes.facecolor": BACKGROUND_WHITE,
        "savefig.facecolor": BACKGROUND_WHITE,
        "savefig.edgecolor": BACKGROUND_WHITE,

        "font.family": font,
        "font.size": 11,

        "axes.titlesize": 16,
        "axes.titleweight": "medium",
        "axes.titlecolor": TEXT_DARK,
        "axes.labelsize": 11,
        "axes.labelcolor": TEXT_DARK,
        "axes.edgecolor": TEXT_MUTED,
        "axes.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": True,
        "axes.spines.bottom": True,

        "xtick.color": TEXT_DARK,
        "ytick.color": TEXT_DARK,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "xtick.direction": "out",
        "ytick.direction": "out",

        "grid.color": TEXT_MUTED,
        "grid.alpha": 0.15,
        "grid.linewidth": 0.5,

        "legend.frameon": False,
        "legend.fontsize": 11,

        "lines.linewidth": 2.5,
        "lines.solid_capstyle": "round",
    }


def plotly_layout() -> dict[str, Any]:
    """Return a Plotly layout dict implementing the house style.

    Use via ``fig.update_layout(**plotly_layout())``.
    """
    font = _pick_available_font()
    return {
        "template": "simple_white",
        "paper_bgcolor": BACKGROUND_WHITE,
        "plot_bgcolor": BACKGROUND_WHITE,
        "font": {"family": font, "color": TEXT_DARK, "size": 12},
        "title": {"font": {"size": 18, "color": TEXT_DARK}},
        "xaxis": {
            "gridcolor": TEXT_MUTED,
            "gridwidth": 0.5,
            "linecolor": TEXT_MUTED,
            "showgrid": False,
            "zeroline": False,
            "ticks": "outside",
        },
        "yaxis": {
            "gridcolor": TEXT_MUTED,
            "gridwidth": 0.5,
            "linecolor": TEXT_MUTED,
            "showgrid": True,
            "zeroline": False,
            "ticks": "outside",
        },
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "bgcolor": "rgba(0,0,0,0)",
        },
        "margin": {"l": 60, "r": 40, "t": 80, "b": 80},
    }

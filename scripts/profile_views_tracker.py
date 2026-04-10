#!/usr/bin/env python3
"""
Enregistre les vues profil GitHub par jour via le total exposé par komarev/ghpvc.
À chaque exécution : delta = total_actuel - total_de_la_veille (snapshot précédent).
Génère un SVG type courbe d'activité (30 derniers jours).
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "profile-views.json"
CHART_PATH = ROOT / "assets" / "profile-views-chart.svg"


def fetch_komarev_total(username: str) -> int:
    q = urllib.parse.urlencode({"username": username, "style": "flat"})
    url = f"https://komarev.com/ghpvc/?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "profile-views-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        svg = r.read().decode("utf-8", errors="replace")
    nums = re.findall(r">(\d+)</text>", svg)
    if not nums:
        raise ValueError("Impossible de lire le compteur dans le SVG komarev.")
    return int(nums[-1])


def load_state() -> dict:
    if not DATA_PATH.exists():
        return {"last_total": None, "daily": {}, "updated_at": None}
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def build_chart_svg(daily: dict, days: int = 30) -> str:
    """Courbe façon contribution graph : fond sombre, ligne violette, aire remplie."""
    today = datetime.now(timezone.utc).date()
    labels: list[str] = []
    values: list[int] = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        key = d.isoformat()
        labels.append(str(d.day))
        values.append(int(daily.get(key, 0)))

    w, h = 800, 220
    pad_l, pad_r, pad_t, pad_b = 56, 24, 48, 40
    inner_w = w - pad_l - pad_r
    inner_h = h - pad_t - pad_b

    ymax = max(values) if values else 0
    if ymax < 3:
        ymax = 3
    y_ticks = ymax + 1

    def x_at(i: int) -> float:
        if len(values) <= 1:
            return pad_l + inner_w / 2
        return pad_l + (i / (len(values) - 1)) * inner_w

    def y_at(v: int) -> float:
        return pad_t + inner_h * (1 - v / ymax)

    points = [(x_at(i), y_at(v)) for i, v in enumerate(values)]
    line_d = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
    area_d = (
        f"M {points[0][0]:.1f},{pad_t + inner_h} L "
        + " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        + f" L {points[-1][0]:.1f},{pad_t + inner_h} Z"
    )

    # Grille horizontale
    grid_lines = []
    for t in range(y_ticks + 1):
        gy = pad_t + inner_h * (1 - t / ymax) if ymax else pad_t + inner_h
        grid_lines.append(
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w - pad_r}" y2="{gy:.1f}" '
            f'stroke="#30363d" stroke-width="1" stroke-dasharray="2,4"/>'
        )
        grid_lines.append(
            f'<text x="{pad_l - 8}" y="{gy + 4:.1f}" fill="#8b949e" font-size="11" '
            f'text-anchor="end" font-family="system-ui,sans-serif">{t}</text>'
        )

    # Points blancs sur la courbe
    dots = "\n    ".join(
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="#c9d1d9" stroke="#7b5ea7" stroke-width="1"/>'
        for px, py in points
    )

    # Labels X (un sur quelques jours pour éviter surcharge)
    step = max(1, len(labels) // 12)
    x_labels = []
    for i, lab in enumerate(labels):
        if i % step != 0 and i != len(labels) - 1:
            continue
        x_labels.append(
            f'<text x="{x_at(i):.1f}" y="{h - 12}" fill="#8b949e" font-size="10" '
            f'text-anchor="middle" font-family="system-ui,sans-serif">{lab}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs>
    <linearGradient id="pvFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#7b5ea7" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="#7b5ea7" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="#0d1117"/>
  <text x="{w / 2}" y="28" fill="#a67fd4" font-size="15" font-weight="600"
        text-anchor="middle" font-family="system-ui,sans-serif">Profile views (par jour)</text>
  <text x="{pad_l}" y="44" fill="#8b949e" font-size="11" font-family="system-ui,sans-serif">Vues</text>
  <text x="{w / 2}" y="{h - 4}" fill="#8b949e" font-size="11" text-anchor="middle"
        font-family="system-ui,sans-serif">Jour du mois (UTC, fenêtre ~30 j.)</text>
  {chr(10).join(grid_lines)}
  <path d="{area_d}" fill="url(#pvFill)" stroke="none"/>
  <polyline fill="none" stroke="#7b5ea7" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="{line_d}"/>
  {dots}
  {chr(10).join(x_labels)}
</svg>
"""


def main() -> None:
    username = os.environ.get("PROFILE_VIEWS_USERNAME", "").strip()
    if not username:
        raise SystemExit("PROFILE_VIEWS_USERNAME manquant.")

    current = fetch_komarev_total(username)
    state = load_state()
    prev = state.get("last_total")

    today_utc = datetime.now(timezone.utc).date().isoformat()

    if prev is None:
        state["last_total"] = current
        state["daily"] = state.get("daily", {})
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Init: total komarev = {current} (prochain run calculera le delta).")
    else:
        delta = max(0, current - prev)
        state["daily"] = state.get("daily", {})
        # Plusieurs runs le même jour UTC : on cumule les increments.
        state["daily"][today_utc] = int(state["daily"].get(today_utc, 0)) + delta
        state["last_total"] = current
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Total: {current} | +{delta} aujourd'hui (cumul {today_utc}: {state['daily'][today_utc]})")

    # Garder ~120 jours max dans daily
    daily = state["daily"]
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=120)).isoformat()
    state["daily"] = {k: v for k, v in daily.items() if k >= cutoff}

    save_state(state)
    svg = build_chart_svg(state["daily"])
    CHART_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHART_PATH.write_text(svg, encoding="utf-8")
    print(f"Écrit: {DATA_PATH.relative_to(ROOT)} et {CHART_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""Shared look and feel for the Streamlit dashboard: CSS, page headers, status pills and stat cards."""
from html import escape
from typing import Iterable, Optional, Sequence, Tuple

import streamlit as st

TONES = {
    "blue": ("#1d4ed8", "#eaf0ff"),
    "green": ("#0f7b4f", "#e6f6ee"),
    "amber": ("#9a5b00", "#fff4dc"),
    "red": ("#b42323", "#fdeaea"),
    "gray": ("#475569", "#eef1f5"),
    "violet": ("#5b3cc4", "#f0ecff"),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --vt-ink: #0f172a;
  --vt-muted: #5b6678;
  --vt-line: #e3e8ef;
  --vt-surface: #ffffff;
  --vt-canvas: #f6f8fb;
  --vt-accent: #1d4ed8;
  --vt-accent-soft: #eaf0ff;
}

html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select {
  font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif;
}
code, pre, .vt-mono { font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace !important; }

/* chrome */
[data-testid="stAppDeployButton"], .stDeployButton, #MainMenu, footer { display: none !important; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"], .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1320px; }

/* headings */
h1, h2, h3, h4 { color: var(--vt-ink); letter-spacing: -0.01em; }
h3 { font-size: 1.12rem !important; font-weight: 650 !important; margin-top: 0.6rem !important; }

/* sidebar */
[data-testid="stSidebar"] { border-right: 1px solid var(--vt-line); }
[data-testid="stSidebarNav"] a span { font-size: 0.9rem; }
[data-testid="stNavSectionHeader"] { font-size: 0.7rem !important; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--vt-muted) !important; font-weight: 600 !important; }

/* metrics as cards */
[data-testid="stMetric"] { background: var(--vt-surface); border: 1px solid var(--vt-line); border-radius: 10px;
  padding: 12px 16px; }
[data-testid="stMetricLabel"] p { font-size: 0.78rem !important; color: var(--vt-muted); font-weight: 500; }
[data-testid="stMetricValue"] { font-size: 1.55rem !important; font-weight: 650; color: var(--vt-ink); }

/* expanders, tabs, tables */
[data-testid="stExpander"] details { border: 1px solid var(--vt-line) !important; border-radius: 10px !important;
  background: var(--vt-surface); }
[data-testid="stExpander"] summary p { font-weight: 550; font-size: 0.92rem; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--vt-line); }
.stTabs [data-baseweb="tab"] { padding: 8px 14px; font-weight: 550; font-size: 0.88rem; }
[data-testid="stDataFrame"] { border: 1px solid var(--vt-line); border-radius: 8px; }

/* custom blocks */
.vt-eyebrow { font-size: 0.74rem; font-weight: 600; letter-spacing: 0.09em; text-transform: uppercase;
  color: var(--vt-accent); margin-bottom: 4px; }
.vt-title { font-size: 1.85rem; font-weight: 700; color: var(--vt-ink); letter-spacing: -0.02em; line-height: 1.2; margin: 0; }
.vt-subtitle { color: var(--vt-muted); font-size: 0.98rem; margin: 6px 0 0 0; max-width: 900px; line-height: 1.55; }
.vt-header { padding-bottom: 14px; margin-bottom: 18px; border-bottom: 1px solid var(--vt-line); }

.vt-pill { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; border-radius: 999px;
  font-size: 0.76rem; font-weight: 600; line-height: 1.6; white-space: nowrap; }
.vt-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }

.vt-card { background: var(--vt-surface); border: 1px solid var(--vt-line); border-radius: 12px; padding: 16px 18px; height: 100%; }
.vt-card-title { margin: 0 0 6px 0; font-size: 0.98rem; font-weight: 650; color: var(--vt-ink); }
.vt-card-body, .vt-card p { margin: 0; color: var(--vt-muted); font-size: 0.88rem !important; line-height: 1.5; }
.vt-label { font-size: 0.76rem; color: var(--vt-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
.vt-grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); margin: 6px 0 14px 0; }
.vt-stat .vt-stat-label { font-size: 0.76rem; color: var(--vt-muted); font-weight: 500; }
.vt-stat .vt-stat-value { font-size: 1.6rem; font-weight: 700; color: var(--vt-ink); line-height: 1.25; }
.vt-stat .vt-stat-hint { font-size: 0.78rem; color: var(--vt-muted); }

.vt-note { border: 1px solid var(--vt-line); border-left: 3px solid var(--vt-accent); background: var(--vt-surface);
  border-radius: 8px; padding: 10px 14px; color: var(--vt-ink); font-size: 0.88rem; line-height: 1.5; margin: 6px 0 12px 0; }
.vt-note b { font-weight: 650; }

.vt-brand { display: flex; align-items: center; gap: 10px; padding: 4px 0 2px 0; }
.vt-brand-name { font-weight: 700; font-size: 1.08rem; color: var(--vt-ink); letter-spacing: -0.01em; }
.vt-brand-tag { font-size: 0.75rem; color: var(--vt-muted); line-height: 1.3; }

/* pipeline stepper */
.vt-steps { display: grid; grid-template-columns: repeat(var(--vt-cols, 7), minmax(0, 1fr)); gap: 8px; margin: 4px 0 16px 0; }
.vt-step { background: var(--vt-surface); border: 1px solid var(--vt-line); border-top: 3px solid var(--vt-accent);
  border-radius: 8px; padding: 9px 10px; min-height: 112px; }
.vt-step.pending { border-top-color: #cbd5e1; opacity: 0.7; }
.vt-step-num { font-size: 0.68rem; font-weight: 600; color: var(--vt-accent); letter-spacing: 0.05em; }
.vt-step-name { font-size: 0.8rem; word-break: break-word; font-weight: 650; color: var(--vt-ink); margin: 1px 0 3px 0; line-height: 1.25; }
.vt-step-ms { font-size: 0.72rem; color: var(--vt-muted); font-family: 'JetBrains Mono', monospace; }
@media (max-width: 1100px) { .vt-steps { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); } }
.vt-step-detail { font-size: 0.74rem; color: var(--vt-muted); margin-top: 4px; line-height: 1.35; }

/* answer statements */
.vt-answer { background: var(--vt-surface); border: 1px solid var(--vt-line); border-radius: 12px; padding: 6px 18px; }
.vt-stmt { display: grid; grid-template-columns: 150px 1fr; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--vt-line); }
.vt-stmt:last-child { border-bottom: none; }
.vt-stmt-text { font-size: 0.92rem; color: var(--vt-ink); line-height: 1.5; }
.vt-stmt-src { font-size: 0.74rem; color: var(--vt-muted); margin-top: 2px; }
@media (max-width: 700px) { .vt-stmt { grid-template-columns: 1fr; gap: 4px; } }

/* trust score */
.vt-trust { background: var(--vt-surface); border: 1px solid var(--vt-line); border-radius: 12px; padding: 16px; text-align: center; }
.vt-trust-label { font-size: 0.76rem; color: var(--vt-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; }
.vt-trust-score { font-size: 3rem; font-weight: 750; line-height: 1.05; margin: 6px 0; }
.vt-trust-bar { height: 6px; background: #edf1f6; border-radius: 99px; overflow: hidden; margin: 8px 0 10px 0; }
.vt-trust-bar > div { height: 100%; border-radius: 99px; }

/* service status cards */
.vt-svc { background: var(--vt-surface); border: 1px solid var(--vt-line); border-radius: 12px; padding: 14px 16px; }
.vt-svc-name { font-weight: 650; font-size: 0.95rem; color: var(--vt-ink); }
.vt-svc-meta { font-size: 0.76rem; color: var(--vt-muted); margin: 3px 0 10px 0; font-family: 'JetBrains Mono', monospace; word-break: break-all; }
.vt-svc-num { font-size: 1.35rem; font-weight: 700; color: var(--vt-ink); }
.vt-svc-sub { font-size: 0.76rem; color: var(--vt-muted); }

.vt-svc-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 2px;
  border-bottom: 1px solid var(--vt-line); font-size: 0.88rem; }
.vt-svc-row:last-child { border-bottom: none; }
.vt-svc-row .vt-mono { font-size: 0.74rem; color: var(--vt-muted); }
.vt-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 10px 0; }
.vt-chip { border: 1px solid var(--vt-line); background: var(--vt-surface); border-radius: 6px; padding: 3px 9px;
  font-size: 0.78rem; color: var(--vt-ink); }
.vt-footer { color: var(--vt-muted); font-size: 0.74rem; line-height: 1.5; }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def pill(text: str, tone: str = "gray", dot: bool = True) -> str:
    fg, bg = TONES.get(tone, TONES["gray"])
    d = f"<span class='vt-dot' style='background:{fg}'></span>" if dot else ""
    return f"<span class='vt-pill' style='color:{fg};background:{bg}'>{d}{escape(str(text))}</span>"


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    html = "<div class='vt-header'>"
    if eyebrow:
        html += f"<div class='vt-eyebrow'>{escape(eyebrow)}</div>"
    html += f"<div class='vt-title'>{escape(title)}</div>"
    if subtitle:
        html += f"<div class='vt-subtitle'>{subtitle}</div>"
    st.markdown(html + "</div>", unsafe_allow_html=True)


def note(text: str, tone: str = "blue") -> None:
    fg, _ = TONES.get(tone, TONES["blue"])
    st.markdown(f"<div class='vt-note' style='border-left-color:{fg}'>{text}</div>", unsafe_allow_html=True)


def stat_cards(items: Sequence[Tuple[str, str, str]]) -> None:
    """items: (label, value, hint)"""
    cards = "".join(
        f"<div class='vt-card vt-stat'><div class='vt-stat-label'>{escape(label)}</div>"
        f"<div class='vt-stat-value'>{escape(str(value))}</div><div class='vt-stat-hint'>{escape(hint)}</div></div>"
        for label, value, hint in items)
    st.markdown(f"<div class='vt-grid'>{cards}</div>", unsafe_allow_html=True)


def info_cards(items: Iterable[Tuple[str, str]], min_width: int = 210) -> None:
    """items: (title, body-html)"""
    cards = "".join(f"<div class='vt-card'><div class='vt-card-title'>{escape(t)}</div><div class='vt-card-body'>{body}</div></div>"
                    for t, body in items)
    st.markdown(f"<div class='vt-grid' style='grid-template-columns:repeat(auto-fit,minmax({min_width}px,1fr))'>{cards}</div>",
                unsafe_allow_html=True)


def chips(items: Iterable[str]) -> None:
    st.markdown("<div class='vt-chips'>" + "".join(f"<span class='vt-chip'>{escape(i)}</span>" for i in items) + "</div>",
                unsafe_allow_html=True)


def section(title: str, caption: Optional[str] = None) -> None:
    st.markdown(f"### {title}")
    if caption:
        st.caption(caption)


def sidebar_brand() -> None:
    import os
    st.logo(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.svg"), size="large")


def demo_notice(feature: str, reason: str) -> None:
    note(f"<b>{escape(feature)} is disabled in the hosted demo.</b> {reason}", tone="amber")

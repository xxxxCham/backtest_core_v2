"""Module-ID: ui.theme.streamlit_css

Purpose: CSS global injecté dans Streamlit pour le thème
"Trading desk sombre, accent cyan-teal" — applique la palette aux composants
Streamlit (boutons, sidebar, métriques, expanders, onglets, inputs, scrollbars).

Role in pipeline: UI theming (Streamlit DOM)

Key components: build_theme_css(), apply_theme()

Inputs: Palette active (ui.theme.colors)

Outputs: Chaîne CSS prête à injecter dans st.markdown(unsafe_allow_html=True)

Dependencies: streamlit, ui.theme.colors

Conventions: Toutes les couleurs et tokens proviennent de ui.theme.colors.
Aucun hex hardcodé ici en dehors de la fonction build_theme_css() qui assemble
les variables CSS root.

Read-if: Vous modifiez le rendu visuel global de l'application.

Skip-if: Vous appelez juste apply_theme() depuis configure_page().
"""

from __future__ import annotations

import streamlit as st

from .colors import (
    FONT_FAMILY_MONO,
    FONT_FAMILY_SANS,
    FONT_SIZES,
    FONT_WEIGHTS,
    RADIUS,
    SPACING,
    ColorPalette,
    get_colors,
)

_THEME_APPLIED_FLAG = "_bc_theme_applied"


def build_theme_css(palette: ColorPalette | None = None) -> str:
    """Construit la feuille de style Streamlit du thème actif.

    Le CSS inclut :
    - variables :root pour palette/typographie/espacements
    - reset des couleurs Streamlit (fond, texte, sidebar)
    - styles cartes / métriques / expanders / alerts
    - 4 niveaux de boutons (primary accent, default, danger, ghost)
    - onglets, inputs, sliders, scrollbars
    - sémantique dynamique (.bc-up, .bc-down, .bc-warn, .bc-info)
    """
    c = get_colors(palette)

    return f"""
<style>
/* ====================================================================
   THEME — Trading desk sombre, accent cyan-teal
   ==================================================================== */
:root {{
    /* --- Fonds --- */
    --bc-bg:            {c["background"]};
    --bc-surface:       {c["surface"]};
    --bc-surface-2:     {c["surface_variant"]};
    --bc-console:       {c.get("console", "#0a0d12")};

    /* --- Lignes --- */
    --bc-border:        {c["border"]};
    --bc-border-subtle: {c.get("border_subtle", "#1d232c")};
    --bc-divider:       {c.get("divider", "rgba(42,49,60,0.6)")};
    --bc-grid:          {c.get("grid_color", "rgba(42,49,60,0.4)")};

    /* --- Texte --- */
    --bc-text:          {c["text"]};
    --bc-text-2:        {c["text_secondary"]};
    --bc-text-3:        {c["text_muted"]};

    /* --- Accent principal (noms legacy conservés pour compat CSS) --- */
    --bc-gold:          {c.get("gold", c["primary"])};
    --bc-gold-bright:   {c.get("gold_bright", c["secondary"])};
    --bc-gold-pale:     {c.get("gold_pale", c["secondary"])};

    /* --- Sémantiques --- */
    --bc-success:       {c["success"]};
    --bc-error:         {c["error"]};
    --bc-warning:       {c["warning"]};
    --bc-info:          {c["info"]};
    --bc-purple:        {c.get("purple", "#a371f7")};

    /* --- Typographie --- */
    --bc-font-sans:  {FONT_FAMILY_SANS};
    --bc-font-mono:  {FONT_FAMILY_MONO};
    --bc-fs-title:   {FONT_SIZES["title_app"]};
    --bc-fs-card:    {FONT_SIZES["title_card"]};
    --bc-fs-caption: {FONT_SIZES["caption"]};
    --bc-fs-text:    {FONT_SIZES["text"]};
    --bc-fs-value:   {FONT_SIZES["value"]};
    --bc-fs-hero:    {FONT_SIZES["value_hero"]};
    --bc-fs-sub:     {FONT_SIZES["subtitle"]};
    --bc-fs-mono:    {FONT_SIZES["mono"]};
    --bc-fw-reg:     {FONT_WEIGHTS["regular"]};
    --bc-fw-sb:      {FONT_WEIGHTS["semibold"]};
    --bc-fw-bold:    {FONT_WEIGHTS["bold"]};

    /* --- Espacements / radii --- */
    --bc-sp-xs: {SPACING["xs"]};
    --bc-sp-sm: {SPACING["sm"]};
    --bc-sp-md: {SPACING["md"]};
    --bc-sp-lg: {SPACING["lg"]};
    --bc-sp-xl: {SPACING["xl"]};
    --bc-r-sm:  {RADIUS["sm"]};
    --bc-r-md:  {RADIUS["md"]};
    --bc-r-lg:  {RADIUS["lg"]};

    /* --- Hauteurs cibles boutons / inputs --- */
    --bc-ctrl-h:    34px;
    --bc-ctrl-h-sm: 28px;
}}

/* ====================================================================
   FONDS GLOBAUX
   ==================================================================== */
html, body, [data-testid="stAppViewContainer"], .stApp {{
    background: var(--bc-bg) !important;
    color: var(--bc-text) !important;
    font-family: var(--bc-font-sans) !important;
    font-size: var(--bc-fs-text);
}}
[data-testid="stAppViewContainer"] > .main {{
    background: transparent;
}}
[data-testid="stAppViewContainer"] .block-container {{
    max-width: none;
    width: 100%;
    padding-top: var(--bc-sp-lg);
    padding-bottom: var(--bc-sp-xl);
    padding-left: var(--bc-sp-xl);
    padding-right: var(--bc-sp-xl);
}}

/* ====================================================================
   SIDEBAR
   ==================================================================== */
[data-testid="stSidebar"] {{
    background: var(--bc-surface) !important;
    border-right: 1px solid var(--bc-border) !important;
}}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
    padding-top: var(--bc-sp-sm);
    padding-left: var(--bc-sp-md);
    padding-right: var(--bc-sp-md);
}}
[data-testid="stSidebar"] * {{
    color: var(--bc-text) !important;
}}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] .caption {{
    color: var(--bc-text-3) !important;
}}

/* ====================================================================
   TYPOGRAPHIE
   ==================================================================== */
[data-testid="stMarkdownContainer"],
[data-testid="stText"],
label, p, li, span, div {{
    color: var(--bc-text);
}}
[data-testid="stCaptionContainer"] {{
    color: var(--bc-text-3) !important;
    font-size: var(--bc-fs-caption);
    letter-spacing: 0.06em;
    text-transform: uppercase;
}}
/* Titres — spécificité renforcée pour battre les styles Streamlit par défaut.
   st.title()/st.subheader() rendent des <h1>/<h2> dans des conteneurs
   très spécifiques (.stApp / data-testid=stHeading) qui surchargeraient
   un simple "h1 {{ ... }}". On chaîne ici les sélecteurs typiques. */
.stApp h1,
[data-testid="stAppViewContainer"] h1,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stHeading"] h1,
section[data-testid="stSidebar"] h1 {{
    font-size: 22px !important;
    font-weight: var(--bc-fw-sb) !important;
    color: var(--bc-text) !important;
    margin-top: var(--bc-sp-xs) !important;
    margin-bottom: var(--bc-sp-sm) !important;
    padding: 0 !important;
    letter-spacing: -0.01em;
    line-height: 1.25;
}}
.stApp h2,
[data-testid="stAppViewContainer"] h2,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stHeading"] h2,
section[data-testid="stSidebar"] h2 {{
    font-size: 14px !important;
    font-weight: var(--bc-fw-sb) !important;
    color: var(--bc-gold-pale) !important;
    margin-top: var(--bc-sp-md) !important;
    margin-bottom: var(--bc-sp-sm) !important;
    padding: 0 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    line-height: 1.3;
}}
.stApp h3,
.stApp h4,
.stApp h5,
.stApp h6,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] h4,
[data-testid="stAppViewContainer"] h5,
[data-testid="stAppViewContainer"] h6,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] h5,
[data-testid="stMarkdownContainer"] h6,
[data-testid="stHeading"] h3,
[data-testid="stHeading"] h4,
[data-testid="stHeading"] h5,
[data-testid="stHeading"] h6,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] h5,
section[data-testid="stSidebar"] h6 {{
    font-size: 12px !important;
    font-weight: var(--bc-fw-sb) !important;
    color: var(--bc-gold-pale) !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: var(--bc-sp-sm) !important;
    margin-bottom: var(--bc-sp-xs) !important;
    padding: 0 !important;
    line-height: 1.3;
}}
hr {{
    border: none !important;
    border-top: 1px solid var(--bc-divider) !important;
    margin: var(--bc-sp-md) 0 !important;
}}
code, pre, kbd, samp {{
    font-family: var(--bc-font-mono) !important;
    font-size: var(--bc-fs-mono);
    color: var(--bc-text);
    background: var(--bc-console);
    border-radius: var(--bc-r-sm);
    padding: 1px 4px;
}}
pre code {{
    background: transparent;
    padding: 0;
}}

/* ====================================================================
   METRICS — caption discrète + valeur grasse
   ==================================================================== */
div[data-testid="stMetric"] {{
    background: var(--bc-surface);
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-md);
    padding: var(--bc-sp-sm) var(--bc-sp-md);
    box-shadow: none;
}}
div[data-testid="stMetricLabel"] {{
    color: var(--bc-text-3) !important;
    font-size: var(--bc-fs-caption) !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: var(--bc-fw-reg) !important;
    margin-bottom: 2px;
}}
div[data-testid="stMetricValue"] {{
    color: var(--bc-gold-bright) !important;
    font-size: var(--bc-fs-hero) !important;
    font-weight: var(--bc-fw-bold) !important;
    line-height: 1.1;
}}
div[data-testid="stMetricDelta"] {{
    font-size: var(--bc-fs-caption) !important;
    font-weight: var(--bc-fw-sb) !important;
}}

/* ====================================================================
   EXPANDERS / CARTES
   ==================================================================== */
div[data-testid="stExpander"] {{
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-md);
    background: var(--bc-surface);
    box-shadow: none;
}}
div[data-testid="stExpander"] summary {{
    padding: var(--bc-sp-sm) var(--bc-sp-md);
    font-weight: var(--bc-fw-sb);
    color: var(--bc-gold-pale);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: var(--bc-fs-card);
}}

/* ====================================================================
   ALERTS / NOTIFICATIONS
   ==================================================================== */
div[data-testid="stAlert"] {{
    border-radius: var(--bc-r-md);
    border: 1px solid var(--bc-border);
    background: var(--bc-surface);
}}
div[data-testid="stAlert"][data-baseweb="notification"] {{
    padding: var(--bc-sp-sm) var(--bc-sp-md);
}}
/* Success / Info / Warning / Error — bordure gauche colorée */
div[data-testid="stAlert"]:has([data-testid="stMarkdownContainer"]) {{
    border-left-width: 3px;
}}
div[role="alert"][data-baseweb="notification"][kind="info"],
.stAlert[data-baseweb="notification"][kind="info"] {{
    border-left-color: var(--bc-info);
}}
.stAlert[data-baseweb="notification"][kind="success"] {{
    border-left-color: var(--bc-success);
}}
.stAlert[data-baseweb="notification"][kind="warning"] {{
    border-left-color: var(--bc-warning);
}}
.stAlert[data-baseweb="notification"][kind="error"] {{
    border-left-color: var(--bc-error);
}}

/* ====================================================================
   BOUTONS — 4 niveaux : primary or / default / danger / ghost
   Tous flat (pas d'ombre, pas de gradient)
   ==================================================================== */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button,
[data-testid="stFormSubmitButton"] > button {{
    background: var(--bc-surface-2) !important;
    color: var(--bc-text) !important;
    border: 1px solid var(--bc-border) !important;
    border-radius: var(--bc-r-md) !important;
    font-weight: var(--bc-fw-sb) !important;
    font-size: var(--bc-fs-text) !important;
    min-height: var(--bc-ctrl-h) !important;
    padding: 4px 12px !important;
    box-shadow: none !important;
    transition: border-color 120ms ease, background 120ms ease, color 120ms ease;
}}
[data-testid="stButton"] > button:hover,
[data-testid="stDownloadButton"] > button:hover,
[data-testid="stFormSubmitButton"] > button:hover {{
    border-color: var(--bc-gold) !important;
    background: var(--bc-surface-2) !important;
    color: var(--bc-text) !important;
}}
[data-testid="stButton"] > button:focus,
[data-testid="stButton"] > button:focus-visible {{
    outline: none !important;
    border-color: var(--bc-gold) !important;
    box-shadow: 0 0 0 1px var(--bc-gold) inset !important;
}}
[data-testid="stButton"] > button:active {{
    background: var(--bc-bg) !important;
    transform: none !important;
}}
[data-testid="stButton"] > button:disabled {{
    opacity: 0.45;
    color: var(--bc-text-3) !important;
    border-color: var(--bc-border-subtle) !important;
    background: var(--bc-surface) !important;
}}

/* Primary — or plein, texte sombre */
[data-testid="stButton"] > button[kind="primary"],
[data-testid="stDownloadButton"] > button[kind="primary"],
[data-testid="stFormSubmitButton"] > button[kind="primary"] {{
    background: var(--bc-gold) !important;
    color: var(--bc-bg) !important;
    border-color: var(--bc-gold) !important;
}}
[data-testid="stButton"] > button[kind="primary"]:hover,
[data-testid="stDownloadButton"] > button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {{
    background: var(--bc-gold-bright) !important;
    color: var(--bc-bg) !important;
    border-color: var(--bc-gold-bright) !important;
}}
[data-testid="stButton"] > button[kind="primary"]:focus,
[data-testid="stButton"] > button[kind="primary"]:focus-visible {{
    box-shadow: 0 0 0 2px var(--bc-gold-bright) inset !important;
}}

/* Secondary — surface relevée + bordure or hover */
[data-testid="stButton"] > button[kind="secondary"],
[data-testid="stDownloadButton"] > button[kind="secondary"],
[data-testid="stFormSubmitButton"] > button[kind="secondary"] {{
    background: var(--bc-surface-2) !important;
    color: var(--bc-text) !important;
    border-color: var(--bc-border) !important;
}}

/* Convention .bc-btn-danger / .bc-btn-ghost via classe parente */
.bc-btn-danger [data-testid="stButton"] > button {{
    background: #3a1f23 !important;
    color: var(--bc-error) !important;
    border: 1px solid #5a2a2f !important;
}}
.bc-btn-danger [data-testid="stButton"] > button:hover {{
    border-color: var(--bc-error) !important;
}}
.bc-btn-ghost [data-testid="stButton"] > button {{
    background: transparent !important;
    color: var(--bc-text-2) !important;
    border: 1px solid var(--bc-border-subtle) !important;
}}
.bc-btn-ghost [data-testid="stButton"] > button:hover {{
    border-color: var(--bc-gold) !important;
    color: var(--bc-text) !important;
}}

/* ====================================================================
   ONGLETS
   ==================================================================== */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
    gap: var(--bc-sp-xs);
    border-bottom: 1px solid var(--bc-border);
    padding-bottom: 0;
    background: transparent;
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
    min-height: var(--bc-ctrl-h);
    padding: 6px 12px;
    border-radius: var(--bc-r-sm) var(--bc-r-sm) 0 0;
    border: 1px solid transparent !important;
    border-bottom: none !important;
    background: transparent !important;
    color: var(--bc-text-2) !important;
    font-weight: var(--bc-fw-sb);
    font-size: var(--bc-fs-text);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    transition: color 120ms ease, border-color 120ms ease, background 120ms ease;
}}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {{
    color: var(--bc-text) !important;
    background: var(--bc-surface) !important;
}}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {{
    background: var(--bc-surface) !important;
    color: var(--bc-gold-bright) !important;
    border-color: var(--bc-border) !important;
    border-bottom-color: var(--bc-surface) !important;
    box-shadow: 0 -2px 0 var(--bc-gold) inset;
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
    background: transparent !important;
}}
[data-testid="stTabs"] [data-baseweb="tab-border"] {{
    background: var(--bc-border) !important;
}}

/* ====================================================================
   INPUTS (text, number, textarea, select, multiselect)
   ==================================================================== */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stDateInput"] input,
[data-testid="stTimeInput"] input,
[data-testid="stChatInput"] textarea {{
    background: var(--bc-console) !important;
    color: var(--bc-text) !important;
    border: 1px solid var(--bc-border) !important;
    border-radius: var(--bc-r-sm) !important;
    font-family: var(--bc-font-mono) !important;
    font-size: var(--bc-fs-text) !important;
    min-height: var(--bc-ctrl-h) !important;
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stDateInput"] input:focus,
[data-testid="stTimeInput"] input:focus,
[data-testid="stChatInput"] textarea:focus {{
    outline: none !important;
    border-color: var(--bc-gold) !important;
    box-shadow: 0 0 0 1px var(--bc-gold) inset !important;
}}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {{
    color: var(--bc-text-3) !important;
}}

/* Selectbox / multiselect (baseweb) */
[data-baseweb="select"] > div {{
    background: var(--bc-console) !important;
    color: var(--bc-text) !important;
    border: 1px solid var(--bc-border) !important;
    border-radius: var(--bc-r-sm) !important;
    min-height: var(--bc-ctrl-h) !important;
}}
[data-baseweb="select"] > div:hover {{
    border-color: var(--bc-gold) !important;
}}
[data-baseweb="select"] [data-baseweb="tag"] {{
    background: var(--bc-surface-2) !important;
    color: var(--bc-text) !important;
    border-radius: var(--bc-r-sm) !important;
}}
[data-baseweb="popover"] ul[role="listbox"] {{
    background: var(--bc-surface) !important;
    border: 1px solid var(--bc-border) !important;
    border-radius: var(--bc-r-sm) !important;
}}
[data-baseweb="popover"] ul[role="listbox"] li:hover,
[data-baseweb="popover"] ul[role="listbox"] li[aria-selected="true"] {{
    background: var(--bc-surface-2) !important;
    color: var(--bc-gold-bright) !important;
}}

/* ====================================================================
   BOUTONS POUSSOIRS — règle universelle pour TOUTE l'application
   Seul le petit marker (case/cercle/track) change de couleur :
   - INACTIF  → bordure rouge, fond transparent
   - ACTIF    → fond accent, bordure accent
   Aucun label/texte n'est jamais coloré.

   On chaîne plusieurs familles de sélecteurs pour couvrir toutes les
   variantes de DOM Streamlit/Baseweb (checkbox, radio, toggle, switch,
   segmented_control, inputs HTML natifs, partout dans l'app).
   ==================================================================== */

/* --- État INACTIF : marker bordure rouge --- */
[data-baseweb="checkbox"] [role="checkbox"],
[data-baseweb="radio"] [role="radio"],
[data-baseweb="switch"] [role="switch"],
[data-testid="stCheckbox"] [role="checkbox"],
[data-testid="stRadio"] [role="radio"],
[data-testid="stToggle"] [role="checkbox"],
[data-testid="stToggle"] [role="switch"],
[data-testid="stRadio"] [data-baseweb="radio"] > div:first-of-type,
[data-testid="stCheckbox"] [data-baseweb="checkbox"] > span:first-of-type {{
    background: transparent !important;
    border-color: var(--bc-error) !important;
    border-width: 1px !important;
    border-style: solid !important;
    box-shadow: none !important;
}}

/* --- État ACTIF : marker fond accent --- */
[data-baseweb="checkbox"] [role="checkbox"][aria-checked="true"],
[data-baseweb="radio"] [role="radio"][aria-checked="true"],
[data-baseweb="switch"] [role="switch"][aria-checked="true"],
[data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"],
[data-testid="stRadio"] [role="radio"][aria-checked="true"],
[data-testid="stToggle"] [role="checkbox"][aria-checked="true"],
[data-testid="stToggle"] [role="switch"][aria-checked="true"],
input[type="checkbox"]:checked,
input[type="radio"]:checked {{
    background: var(--bc-gold) !important;
    border-color: var(--bc-gold) !important;
}}

/* Inputs HTML natifs non-cochés — fallback si l'app n'utilise pas baseweb */
input[type="checkbox"]:not(:checked),
input[type="radio"]:not(:checked) {{
    border-color: var(--bc-error) !important;
    background: transparent !important;
}}

/* Point intérieur d'un radio sélectionné — contraste sombre sur or */
[data-baseweb="radio"] [role="radio"][aria-checked="true"] > div,
[data-testid="stRadio"] [role="radio"][aria-checked="true"] > div {{
    background: var(--bc-bg) !important;
}}

/* Coche SVG d'une checkbox cochée — sombre sur or */
[data-baseweb="checkbox"] [role="checkbox"][aria-checked="true"] svg,
[data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"] svg {{
    color: var(--bc-bg) !important;
    fill: var(--bc-bg) !important;
}}

/* ====================================================================
   TOGGLE SWITCH (st.toggle / segmented switch)
   - OFF : track rouge / handle clair
   - ON  : track or   / handle clair
   ==================================================================== */

/* Toggle OFF — track rouge */
[data-testid="stToggle"] [role="checkbox"][aria-checked="false"],
[data-testid="stToggle"] [role="switch"][aria-checked="false"],
[data-baseweb="switch"] [role="switch"][aria-checked="false"],
[data-testid="stToggle"] [data-baseweb="checkbox"] > div:first-of-type[aria-checked="false"] {{
    background: var(--bc-error) !important;
    border-color: var(--bc-error) !important;
}}

/* Toggle ON — track or */
[data-testid="stToggle"] [role="checkbox"][aria-checked="true"],
[data-testid="stToggle"] [role="switch"][aria-checked="true"],
[data-baseweb="switch"] [role="switch"][aria-checked="true"],
[data-testid="stToggle"] [data-baseweb="checkbox"] > div:first-of-type[aria-checked="true"] {{
    background: var(--bc-gold) !important;
    border-color: var(--bc-gold) !important;
}}

/* Handle (rond) du toggle — toujours clair, quel que soit l'état */
[data-testid="stToggle"] [role="checkbox"] > div,
[data-testid="stToggle"] [role="switch"] > div,
[data-baseweb="switch"] [role="switch"] > div {{
    background: var(--bc-text) !important;
}}

/* ====================================================================
   SEGMENTED CONTROL / BUTTON GROUP (st.segmented_control / button group)
   Sous-tendu par un radio group : option active → accent, inactive → bordure
   discrète. (On NE met PAS de fond rouge sur les segments inactifs,
   sinon toute la barre devient rouge — règle "discrète" pour ce cas.)
   ==================================================================== */
[data-testid="stSegmentedControl"] [role="radio"],
[data-baseweb="button-group"] button[role="radio"] {{
    background: transparent !important;
    border: 1px solid var(--bc-border) !important;
    color: var(--bc-text-2) !important;
}}
[data-testid="stSegmentedControl"] [role="radio"][aria-checked="true"],
[data-baseweb="button-group"] button[role="radio"][aria-checked="true"] {{
    background: var(--bc-gold) !important;
    border-color: var(--bc-gold) !important;
    color: var(--bc-bg) !important;
}}

/* ====================================================================
   SAFETY NET — wrapper TEXTE seulement (pas le marker)
   ==================================================================== */

/* On cible le DERNIER div enfant du label QUI A des frères → c'est le
   wrapper de texte. Le marker visuel est toujours le PREMIER enfant.
   On évite ainsi de toucher le marker tout en gardant le label propre. */
[data-testid="stCheckbox"] label > div:last-child:not(:only-child),
[data-testid="stRadio"] label > div:last-child:not(:only-child),
[data-testid="stToggle"] label > div:last-child:not(:only-child),
[data-testid="stCheckbox"] [data-testid="stMarkdownContainer"],
[data-testid="stRadio"] [data-testid="stMarkdownContainer"],
[data-testid="stToggle"] [data-testid="stMarkdownContainer"],
[data-testid="stCheckbox"] label p,
[data-testid="stRadio"] label p,
[data-testid="stToggle"] label p {{
    background: transparent !important;
    color: var(--bc-text) !important;
}}

/* Sliders */
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {{
    background: var(--bc-gold) !important;
    border-color: var(--bc-gold-bright) !important;
}}
[data-testid="stSlider"] [data-baseweb="slider"] > div > div > div:nth-child(1) {{
    background: var(--bc-gold) !important;
}}

/* ====================================================================
   TABLES / DATAFRAMES
   ==================================================================== */
[data-testid="stTable"] table,
[data-testid="stDataFrame"] {{
    background: var(--bc-surface) !important;
    border: 1px solid var(--bc-border) !important;
    border-radius: var(--bc-r-sm) !important;
    color: var(--bc-text) !important;
    font-size: var(--bc-fs-text);
}}
[data-testid="stTable"] thead th {{
    background: var(--bc-surface-2) !important;
    color: var(--bc-text-2) !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: var(--bc-fs-caption) !important;
    border-bottom: 1px solid var(--bc-border) !important;
}}
[data-testid="stTable"] tbody td {{
    border-bottom: 1px solid var(--bc-divider) !important;
    color: var(--bc-text) !important;
    padding: var(--bc-sp-xs) var(--bc-sp-sm);
}}

/* ====================================================================
   CODE BLOCKS / CONSOLES
   ==================================================================== */
[data-testid="stCodeBlock"] {{
    background: var(--bc-console) !important;
    border: 1px solid var(--bc-border) !important;
    border-radius: var(--bc-r-sm) !important;
}}
[data-testid="stCodeBlock"] pre {{
    background: transparent !important;
    color: var(--bc-text) !important;
    font-family: var(--bc-font-mono) !important;
    font-size: var(--bc-fs-mono);
}}

/* ====================================================================
   PROGRESS / SPINNER
   ==================================================================== */
[data-testid="stProgress"] > div > div {{
    background: var(--bc-gold) !important;
}}
[data-testid="stProgress"] > div {{
    background: var(--bc-surface-2) !important;
}}
[data-testid="stSpinner"] > div {{
    border-top-color: var(--bc-gold) !important;
}}

/* ====================================================================
   HEADER STREAMLIT — masquer le bandeau natif
   ==================================================================== */
header[data-testid="stHeader"] {{
    background: transparent !important;
    height: 0 !important;
    min-height: 0 !important;
}}
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
#MainMenu,
footer {{
    display: none !important;
}}
[data-testid="stToolbar"] {{
    background: transparent !important;
    box-shadow: none !important;
}}
[data-testid="stSidebarNav"] {{
    display: none !important;
}}

/* Bouton expand/collapse sidebar — visible et au thème */
[data-testid="stSidebar"] button[kind="header"],
[data-testid="stSidebar"] button[kind="headerNoPadding"],
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"] {{
    background: var(--bc-surface) !important;
    border: 1px solid var(--bc-border) !important;
    border-radius: var(--bc-r-sm) !important;
    box-shadow: none !important;
    color: var(--bc-text) !important;
}}
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"] {{
    position: fixed !important;
    top: 0.6rem;
    left: 0.6rem;
    z-index: 100000 !important;
}}
[data-testid="stSidebar"] button[kind="header"] svg,
[data-testid="stSidebar"] button[kind="headerNoPadding"] svg,
[data-testid="stExpandSidebarButton"] svg,
[data-testid="collapsedControl"] svg {{
    fill: var(--bc-text) !important;
}}

/* ====================================================================
   SCROLLBARS — fines, custom
   ==================================================================== */
* {{
    scrollbar-width: thin;
    scrollbar-color: var(--bc-border) transparent;
}}
*::-webkit-scrollbar {{
    width: 8px;
    height: 8px;
}}
*::-webkit-scrollbar-track {{
    background: transparent;
}}
*::-webkit-scrollbar-thumb {{
    background: var(--bc-border);
    border-radius: 4px;
}}
*::-webkit-scrollbar-thumb:hover {{
    background: var(--bc-gold);
}}

/* ====================================================================
   NAVIGATION CUSTOM (sidebar workspace nav) — alignée or
   ==================================================================== */
.bc-sidebar-nav-block {{
    margin: var(--bc-sp-sm) 0 var(--bc-sp-md) 0;
    padding: var(--bc-sp-md);
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-md);
    background: var(--bc-surface);
}}
.bc-sidebar-nav-title {{
    font-size: var(--bc-fs-caption);
    font-weight: var(--bc-fw-sb);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--bc-gold-pale);
    margin-bottom: var(--bc-sp-sm);
}}
.bc-sidebar-nav-links {{
    display: grid;
    gap: var(--bc-sp-xs);
}}
.bc-nav-link {{
    display: block;
    text-decoration: none;
    border-radius: var(--bc-r-sm);
    padding: 6px 10px;
    font-weight: var(--bc-fw-sb);
    font-size: var(--bc-fs-text);
    color: var(--bc-text-2) !important;
    background: var(--bc-surface-2);
    border: 1px solid var(--bc-border-subtle);
    transition: border-color 120ms ease, color 120ms ease, background 120ms ease;
}}
.bc-nav-link:hover {{
    border-color: var(--bc-gold);
    color: var(--bc-text) !important;
    background: var(--bc-surface);
}}
.bc-nav-link.active {{
    background: var(--bc-surface);
    border-color: var(--bc-gold);
    color: var(--bc-gold-bright) !important;
    box-shadow: 0 -2px 0 var(--bc-gold) inset;
}}

/* ====================================================================
   ACTION BAR (cf. ui.main MAIN_ACTION_BAR_CSS) — neutralisée par l'ancre
   ==================================================================== */
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) {{
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-md);
    padding: var(--bc-sp-md);
    background: var(--bc-surface);
    margin: var(--bc-sp-sm) 0 var(--bc-sp-md) 0;
    box-shadow: none;
}}
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) [data-testid="stButton"] > button {{
    min-height: var(--bc-ctrl-h) !important;
    border-radius: var(--bc-r-sm) !important;
    font-weight: var(--bc-fw-sb) !important;
    letter-spacing: 0.02em;
}}
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) h3 {{
    margin-bottom: var(--bc-sp-xs);
}}

/* ====================================================================
   SÉMANTIQUE DYNAMIQUE — classes utilitaires
   "La coloration sémantique est le cœur du système"
   ==================================================================== */
.bc-up, .bc-positive, .bc-success    {{ color: var(--bc-success) !important; }}
.bc-down, .bc-negative, .bc-error    {{ color: var(--bc-error) !important; }}
.bc-warn, .bc-warning, .bc-degraded  {{ color: var(--bc-warning) !important; }}
.bc-info, .bc-starting               {{ color: var(--bc-info) !important; }}
.bc-stopped, .bc-never, .bc-muted    {{ color: var(--bc-text-3) !important; }}
.bc-hero, .bc-price                  {{ color: var(--bc-gold-bright) !important;
                                       font-weight: var(--bc-fw-bold);
                                       font-size: var(--bc-fs-hero); }}
.bc-gold                              {{ color: var(--bc-gold) !important; }}
.bc-purple                            {{ color: var(--bc-purple) !important; }}
.bc-caption                           {{ color: var(--bc-text-3) !important;
                                       font-size: var(--bc-fs-caption);
                                       text-transform: uppercase;
                                       letter-spacing: 0.08em; }}
.bc-mono                              {{ font-family: var(--bc-font-mono) !important;
                                       font-size: var(--bc-fs-mono); }}

/* Point d'état coloré */
.bc-dot {{
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}}
.bc-dot.up      {{ background: var(--bc-success); }}
.bc-dot.down    {{ background: var(--bc-error); }}
.bc-dot.warn    {{ background: var(--bc-warning); }}
.bc-dot.info    {{ background: var(--bc-info); }}
.bc-dot.muted   {{ background: var(--bc-text-3); }}
.bc-dot.gold    {{ background: var(--bc-gold); }}

/* Carte / panneau libre (HTML custom) */
.bc-card {{
    background: var(--bc-surface);
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-md);
    padding: 10px 14px;
    margin-bottom: var(--bc-sp-md);
}}
.bc-card-title {{
    font-size: var(--bc-fs-card);
    font-weight: var(--bc-fw-sb);
    color: var(--bc-gold-pale);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: var(--bc-sp-sm);
}}

/* ====================================================================
   GRADUATION P1→P6 — paliers primaires + run actif séparé
   ==================================================================== */
.bc-grad-phase-section {{
    margin: var(--bc-sp-md) 0 var(--bc-sp-sm) 0;
}}
.bc-grad-section-head {{
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: var(--bc-sp-md);
    margin-bottom: var(--bc-sp-sm);
}}
.bc-grad-eyebrow,
.bc-grad-phase-main-label {{
    color: var(--bc-text-3);
    font-size: var(--bc-fs-caption);
    font-weight: var(--bc-fw-sb);
    text-transform: uppercase;
    letter-spacing: 0.08em;
}}
.bc-grad-section-title {{
    color: var(--bc-text);
    font-size: var(--bc-fs-sub);
    font-weight: var(--bc-fw-bold);
    line-height: 1.2;
}}
.bc-grad-p1-total {{
    color: var(--bc-text-2);
    font-size: var(--bc-fs-caption);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    white-space: nowrap;
}}
.bc-grad-p1-total strong {{
    color: var(--bc-gold-bright);
    font-size: var(--bc-fs-text);
}}
.bc-grad-phase-grid {{
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: var(--bc-sp-sm);
}}
.bc-grad-phase-card {{
    min-height: 128px;
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-md);
    background: var(--bc-surface);
    padding: var(--bc-sp-sm) var(--bc-sp-md);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}}
.bc-grad-phase-card.is-active {{
    border-color: var(--bc-gold);
    box-shadow: 0 0 0 1px var(--bc-gold) inset;
    background: var(--bc-surface-2);
}}
.bc-grad-phase-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--bc-sp-sm);
}}
.bc-grad-phase-code {{
    color: var(--bc-gold-bright);
    font-weight: var(--bc-fw-bold);
    font-size: var(--bc-fs-card);
}}
.bc-grad-phase-name {{
    color: var(--bc-text-3);
    font-size: var(--bc-fs-caption);
    text-align: right;
}}
.bc-grad-phase-value {{
    color: var(--bc-gold-bright);
    font-size: var(--bc-fs-hero);
    font-weight: var(--bc-fw-bold);
    line-height: 1;
    margin-top: var(--bc-sp-xs);
}}
.bc-grad-phase-detail {{
    color: var(--bc-text-2);
    font-size: var(--bc-fs-caption);
    line-height: 1.35;
}}
.bc-grad-phase-detail strong {{
    color: var(--bc-text);
}}
.bc-grad-timeline {{
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 4px;
    margin: var(--bc-sp-sm) 0 var(--bc-sp-md) 0;
}}
.bc-grad-step {{
    border-top: 2px solid var(--bc-border);
    padding-top: 6px;
    color: var(--bc-text-3);
}}
.bc-grad-step.is-done {{
    border-top-color: var(--bc-success);
    color: var(--bc-text-2);
}}
.bc-grad-step.is-active {{
    border-top-color: var(--bc-gold);
    color: var(--bc-gold-bright);
}}
.bc-grad-phase,
.bc-grad-label {{
    display: block;
    font-size: var(--bc-fs-caption);
    line-height: 1.25;
}}
.bc-grad-phase {{
    font-weight: var(--bc-fw-bold);
}}
.bc-grad-run-progress {{
    display: grid;
    gap: 6px;
    padding: 8px 10px;
    border-top: 1px solid var(--bc-border);
    background: var(--bc-console);
}}
.bc-grad-run-progress-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--bc-sp-sm);
    color: var(--bc-text-2);
    font-size: var(--bc-fs-caption);
    font-weight: var(--bc-fw-sb);
}}
.bc-grad-run-progress-head strong {{
    color: var(--bc-info);
}}
.bc-grad-run-progress-track {{
    height: 8px;
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-sm);
    background: var(--bc-surface-2);
    overflow: hidden;
}}
.bc-grad-run-progress-fill {{
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, var(--bc-info), var(--bc-success));
}}
.bc-grad-detail-list {{
    display: grid;
    gap: 1px;
    border: 1px solid var(--bc-border);
    border-radius: var(--bc-r-sm);
    overflow: hidden;
    background: var(--bc-border);
}}
.bc-grad-detail-row {{
    display: grid;
    grid-template-columns: minmax(160px, 0.35fr) minmax(0, 1fr);
    gap: var(--bc-sp-sm);
    padding: 8px 10px;
    background: var(--bc-surface);
}}
.bc-grad-detail-row span {{
    color: var(--bc-text-3);
    font-size: var(--bc-fs-caption);
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}
.bc-grad-detail-row strong {{
    color: var(--bc-text);
    font-weight: var(--bc-fw-sb);
    overflow-wrap: anywhere;
}}
.bc-grad-detail-empty {{
    padding: 8px 10px;
    color: var(--bc-text-3);
    background: var(--bc-surface);
}}
@media (max-width: 1000px) {{
    .bc-grad-phase-grid,
    .bc-grad-timeline {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .bc-grad-section-head,
    .bc-grad-detail-row {{
        display: block;
    }}
    .bc-grad-p1-total {{
        margin-top: var(--bc-sp-xs);
        white-space: normal;
    }}
}}

/* ====================================================================
   COMPATIBILITÉ — neutralise les vieux gradients/ombres hardcodés
   (rétro-compat avec divers st.markdown injectés ailleurs)
   ==================================================================== */
div[style*="border-left: 4px solid rgba(0,0,0,0.2)"] code,
div[style*="border-left: 4px solid #666"] code {{
    color: var(--bc-text) !important;
    background-color: var(--bc-console) !important;
    border: 1px solid var(--bc-border) !important;
}}
</style>
"""


def apply_theme(palette: ColorPalette | None = None, *, force: bool = False) -> None:
    """Injecte le CSS du thème dans la page Streamlit courante.

    Appel idempotent par défaut (un seul rendu CSS par session Streamlit).
    Utiliser ``force=True`` pour ré-injecter (utile en hot reload).
    """
    if not force and st.session_state.get(_THEME_APPLIED_FLAG):
        return
    st.markdown(build_theme_css(palette), unsafe_allow_html=True)
    st.session_state[_THEME_APPLIED_FLAG] = True


__all__ = ["build_theme_css", "apply_theme"]

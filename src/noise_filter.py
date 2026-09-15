"""Filtri di rumore applicati PRIMA dello scoring.

Tre famiglie di rumore documentate nei digest W19-W38:

1. **Commenti di open peer review** contati come paper autonomi (falla EGUsphere,
   W34 x3, W35, W36): un preprint in discussione aperta genera un DOI per ogni
   replica e per ogni commento del referee. OpenAlex li marca `type: "peer-review"`,
   e il DOI EGUsphere porta il suffisso `-acN` / `-rcN` / `-scN` / `-ccN`.
2. **Errata, editoriali, paratesti**: `type` dedicato in OpenAlex.
3. **Omonimia d'autore dentro lo stesso profilo OpenAlex** (caso Ferrini,
   `A5048515755`, che fonde l'arboricoltore e un informatico dei Graph Neural
   Networks): il rimedio non e sostituire l'ID -- ce n'e uno solo e contiene
   entrambi -- ma scartare i lavori la cui *fonte* e un preprint server o un
   repository istituzionale. Il prof. Ferrini pubblica su riviste peer-reviewed,
   l'informatico su arXiv. Filtro su `source`, non sul titolo: nessun falso
   negativo di lessico.

Riferimento: `monitoraggio-letteratura/fonti/03_autori_chiave.md`, sezione
"FERRINI - trovata la causa dell'omonimia" (10/09/2026).
"""
from __future__ import annotations

import re
from typing import Any

# --- 1 e 2: tipi di work che non sono paper -------------------------------
DEFAULT_EXCLUDED_WORK_TYPES = {
    "peer-review",
    "erratum",
    "paratext",
    "editorial",
    "letter",
    "grant",
    "retraction",
}

# Titoli tipici di una replica / commento in open review
DEFAULT_EXCLUDED_TITLE_PREFIXES = (
    "reply on",
    "reply to",
    "comment on",
    "comments on",
    "author comment",
    "referee comment",
    "short comment",
    "community comment",
    "correction to",
    "corrigendum to",
    "erratum to",
    "response to",
    "editorial comment",
)

# DOI dei commenti di discussione aperta (Copernicus / EGUsphere e simili)
DEFAULT_EXCLUDED_DOI_PATTERNS = (
    r"egusphere-\d{4}-\d+-(ac|rc|sc|cc|ec)\d+",
    r"\bbg-\d{4}-\d+-(ac|rc|sc|cc)\d+",
    r"\bhess-\d{4}-\d+-(ac|rc|sc|cc)\d+",
)

# --- 3: fonti che non sono sede di pubblicazione peer-reviewed ------------
DEFAULT_PREPRINT_SOURCE_PATTERNS = (
    "arxiv",
    "biorxiv",
    "medrxiv",
    "ssrn",
    "research square",
    "researchsquare",
    "preprints.org",
    "hal ",
    "zenodo",
    "figshare",
    "iris",
    "vbn",
    "forskningsportal",
    "institutional research information",
    "repository",
    "air -",
    "flore",
    "unipi",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").lower().strip()


def is_noise(paper: dict[str, Any], rules: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Return (True, reason) se il paper va scartato prima dello scoring."""
    rules = rules or {}
    nf = rules.get("noise_filters") or {}

    excluded_types = {
        _norm(t) for t in (nf.get("excluded_work_types") or DEFAULT_EXCLUDED_WORK_TYPES)
    }
    title_prefixes = tuple(
        _norm(p) for p in (nf.get("excluded_title_prefixes") or DEFAULT_EXCLUDED_TITLE_PREFIXES)
    )
    doi_patterns = tuple(
        nf.get("excluded_doi_patterns") or DEFAULT_EXCLUDED_DOI_PATTERNS
    )

    wtype = _norm(paper.get("work_type", ""))
    if wtype and wtype in excluded_types:
        return True, f"work_type={wtype}"

    title = _norm(paper.get("title", ""))
    for p in title_prefixes:
        if p and title.startswith(p):
            return True, f"title_prefix={p!r}"

    doi = _norm(paper.get("doi", ""))
    for pat in doi_patterns:
        if doi and re.search(pat, doi):
            return True, f"doi_pattern={pat}"

    return False, ""


def is_preprint_or_repository(paper: dict[str, Any], rules: dict[str, Any] | None = None) -> bool:
    """True se la fonte del paper e un preprint server o un repository.

    Usata per NEGARE il bonus di autore-chiave (+5) ai lavori che finiscono nel
    profilo fuso di un autore omonimo. Non scarta il paper: se il contenuto vale
    per le keyword, resta in digest col suo punteggio.
    """
    rules = rules or {}
    nf = rules.get("noise_filters") or {}
    patterns = tuple(
        _norm(p) for p in (nf.get("preprint_source_patterns") or DEFAULT_PREPRINT_SOURCE_PATTERNS)
    )

    haystack = " ".join(
        _norm(paper.get(k, "")) for k in ("journal", "source_host", "source_type")
    )
    if _norm(paper.get("source_type")) == "repository":
        return True
    return any(p and p in haystack for p in patterns)


def filter_noise(
    papers: list[dict[str, Any]], rules: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Return (papers_kept, [(title, reason), ...] degli scartati)."""
    kept: list[dict[str, Any]] = []
    dropped: list[tuple[str, str]] = []
    for p in papers:
        noise, reason = is_noise(p, rules)
        if noise:
            dropped.append(((p.get("title") or "")[:90], reason))
        else:
            kept.append(p)
    return kept, dropped

"""Apply scoring rules to a paper.

For each area in rules.json, sum keyword matches in title + abstract.
Pick the area with highest score. Apply bonuses (OA, key author, citation count).
"""
from __future__ import annotations

import re
from typing import Any

#: Marcatore interno: area attribuita dall'autore-chiave, non dalle keyword.
AREA_BY_AUTHOR_FLAG = "area-assegnata-per-autore"

try:
    from src.noise_filter import is_preprint_or_repository
except ImportError:  # esecuzione diretta senza package
    from noise_filter import is_preprint_or_repository


def _norm(text: str) -> str:
    """Lowercase, strip extra whitespace."""
    return re.sub(r"\s+", " ", text or "").lower().strip()


def _has_phrase(text: str, phrase: str) -> bool:
    """Check if a phrase appears in text (case-insensitive, word-boundary safe)."""
    text_norm = _norm(text)
    phrase_norm = _norm(phrase)
    if not phrase_norm:
        return False
    # Use simple substring match — adequate for our keyword sizes
    return phrase_norm in text_norm


def _suppress_substring_hits(hits: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Scarta una keyword positiva quando e sottostringa di un'altra che ha pure
    fatto centro nella stessa area.

    Introdotta il 22/09/2026 insieme a `urban forest`. `_has_phrase` fa un match
    di sottostringa nuda, quindi un testo che dice *urban forestry* fa scattare
    anche *urban forest*: senza questa passata il paper prenderebbe +3 E +2 per
    la stessa frase, e gli score piu gonfiati sarebbero proprio quelli dei lavori
    piu a tema -- non confrontabili con le settimane precedenti.

    Vale solo fra keyword positive: una negativa non va mai soppressa, perche il
    suo compito e togliere punti, e una coppia come `deforestation` dentro un
    testo che dice anche `forestation` deve continuare a pesare.
    """
    positives = [(kw, w) for kw, w in hits if w > 0]
    kept: list[tuple[str, int]] = []
    for kw, w in hits:
        if w <= 0:
            kept.append((kw, w))
            continue
        kw_n = _norm(kw)
        covered = any(
            kw_n != _norm(other) and kw_n in _norm(other)
            for other, _ in positives
        )
        if not covered:
            kept.append((kw, w))
    return kept


def score_paper(paper: dict[str, Any], rules: dict[str, Any]) -> tuple[int, str, list[str]]:
    """Return (best_score, best_area, matched_keywords).

    rules schema (config/rules.json):
    {
      "areas": {
        "verde_urbano": {
          "positive_high": ["urban forestry", ...],   # weight +3
          "positive_medium": [...],                    # weight +2
          "positive_low": [...],                       # weight +1
          "negative": [...]                            # weight -2
        },
        "vta": { ... }
      },
      "key_authors": [{"name": "Henrik Sjöman", "openalex_id": "A...", "areas": [...]}],
      "min_score_threshold": 5
    }
    """
    text = (paper.get("title", "") or "") + " " + (paper.get("abstract", "") or "")

    best_score = 0
    best_area = "uncategorized"
    matched_keywords: list[str] = []
    best_had_high = False

    # Per-area scoring
    for area, area_rules in (rules.get("areas") or {}).items():
        hits: list[tuple[str, int]] = []
        for kw in area_rules.get("positive_high", []) or []:
            if _has_phrase(text, kw):
                hits.append((kw, 3))
        for kw in area_rules.get("positive_medium", []) or []:
            if _has_phrase(text, kw):
                hits.append((kw, 2))
        for kw in area_rules.get("positive_low", []) or []:
            if _has_phrase(text, kw):
                hits.append((kw, 1))
        for kw in area_rules.get("negative", []) or []:
            if _has_phrase(text, kw):
                hits.append((kw, -2))

        hits = _suppress_substring_hits(hits)

        score = sum(w for _, w in hits)
        had_high = any(w == 3 for _, w in hits)
        kw_for_area = [f"{'+' if w > 0 else ''}{w}:{kw}" for kw, w in hits]

        if score > best_score:
            best_score = score
            best_area = area
            matched_keywords = kw_for_area
            best_had_high = had_high

    # If the paper got 0 in all areas but has a key author, classify by author area
    area_by_author = False
    if best_score == 0:
        author_match = _check_key_author(paper, rules)
        if author_match:
            best_area = author_match["areas"][0] if author_match.get("areas") else best_area
            area_by_author = True

    # Bonuses (apply only if at least one area matched OR key author)
    bonus = 0
    bonus_notes: list[str] = []

    if paper.get("is_oa"):
        bonus += 1
        bonus_notes.append("+1:OA")

    author_match = _check_key_author(paper, rules)
    if author_match and is_preprint_or_repository(paper, rules):
        # Profilo OpenAlex fuso con un omonimo (caso Ferrini): i lavori
        # dell'altra persona escono su preprint server e repository. Il paper
        # resta in lizza per le sue keyword, ma senza il +5 non passa la soglia
        # solo perche il cognome coincide.
        author_match = None
        matched_keywords.append("author_bonus_negato:fonte-preprint-o-repository")

    if author_match:
        bonus += 5
        bonus_notes.append(f"+5:author={author_match.get('name', '')}")

    cited = paper.get("cited_by_count", 0) or 0
    if cited >= 5:
        bonus += 1
        bonus_notes.append(f"+1:cited({cited})")

    if best_score > 0 or author_match:
        best_score += bonus
        matched_keywords.extend(bonus_notes)

    # Marcatore (22/09/2026). Quando un lavoro non prende un solo punto di
    # keyword ma ha un autore monitorato, l'area gliela da l'autore. E voluto,
    # ma nel digest produce un'illusione ottica: in W39 la sezione VTA conteneva
    # un paper di percezione estetica del paesaggio, finito li solo perche Hauer
    # e catalogato VTA. Chi legge di corsa crede che il canale VTA abbia
    # prodotto qualcosa. Il digest ora lo dichiara.
    if area_by_author and author_match:
        matched_keywords.append(AREA_BY_AUTHOR_FLAG)

    # Regola anti-falso-positivo (15/09/2026). Un hit che raggiunge la soglia
    # senza una sola keyword `positive_high` dell'area e fatto di termini
    # generici: la combinazione "ecosystem services" + "Italy" + "Italian" + OA
    # fa 5 esatti, cioe qualunque paper ambientale italiano in open access
    # passava. Caso da cui nasce: W38, paper sulla transizione pascolo-foresta
    # nelle Alpi, zero parole urbane. Un autore-chiave la scavalca: se firma
    # uno dei cinque, il lavoro interessa comunque.
    if rules.get("require_positive_high") and not best_had_high and not author_match:
        matched_keywords.append("declassato:nessuna-keyword-forte")
        return 0, best_area, matched_keywords

    return best_score, best_area, matched_keywords


def _check_key_author(paper: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any] | None:
    """Return the matching key-author entry if any.

    Ordine di preferenza, dal piu affidabile al meno:

    1. **OpenAlex author ID** (`paper["author_ids"]` contro `ka["openalex_id"]` e
       `ka["openalex_id_alt"]`). E l'unico match senza ambiguita, e copre i
       profili spezzati (Konijnendijk e Salbitano hanno due ID a testa).
    2. **Nome e cognome entrambi presenti** nella stessa stringa d'autore.
       Fallback per EuropePMC / CrossRef / RSS, che non danno gli ID.

    Il match sul **solo cognome** e stato rimosso il 15/09/2026: faceva scattare
    il bonus +5 su qualunque omonimo al mondo -- un secondo canale di falsi
    positivi indipendente dal profilo OpenAlex fuso di Ferrini, e mai rilevato
    prima perche i due difetti producevano lo stesso sintomo.
    """
    key_authors = rules.get("key_authors", []) or []

    # 1. match per ID OpenAlex
    paper_ids = {
        (i or "").strip()
        for i in (paper.get("author_ids") or [])
        if i
    }
    if paper_ids:
        for ka in key_authors:
            ka_ids = {
                (ka.get("openalex_id") or "").strip(),
                (ka.get("openalex_id_alt") or "").strip(),
            } - {""}
            if ka_ids & paper_ids:
                return ka
        # Gli ID c'erano e nessuno corrisponde: la risposta e no, e non si
        # ripiega sul nome. Altrimenti due persone che si chiamano davvero allo
        # stesso modo restano indistinguibili -- caso verificato il 15/09/2026:
        # "Richard J. Hauer" (urban forestry) e "F. Richard Hauer" (ecologia
        # fluviale) sono nella STESSA universita.
        return None

    # 2. fallback: nome E cognome nella stessa stringa d'autore
    paper_authors_norm = [_norm(a) for a in (paper.get("authors") or [])]
    for ka in key_authors:
        ka_name_norm = _norm(ka.get("name", ""))
        if not ka_name_norm:
            continue
        parts = [t for t in ka_name_norm.split() if len(t) > 1]
        if not parts:
            continue
        surname = parts[-1]
        given = parts[0]
        for pa in paper_authors_norm:
            pa_tokens = set(pa.replace(".", " ").split())
            if surname in pa_tokens and (
                given in pa_tokens or any(t.startswith(given[0]) and len(t) <= 2 for t in pa_tokens)
            ):
                return ka
    return None

"""Smoke test E2E del motore.

Test offline: non chiama API esterne, simula i dati.
Verifica che la pipeline (deduplicate → score → write_digest → save_seen)
funzioni end-to-end con dati sintetici.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Add repo root to path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from src.deduplicate import deduplicate_papers
from src.digest_writer import write_digest
from src.scoring import score_paper
from src.seen import load_seen, save_seen


def _sample_paper(doi: str, title: str, abstract: str, authors: list[str],
                  is_oa: bool = True, journal: str = "Forests",
                  year: int = 2026, source: str = "openalex") -> dict:
    return {
        "title": title,
        "doi": doi.lower() if doi else "",
        "authors": authors,
        "year": year,
        "publication_date": f"{year}-04-01",
        "abstract": abstract,
        "journal": journal,
        "openalex_source_id": "S71324801",
        "is_oa": is_oa,
        "oa_url": f"https://doi.org/{doi}" if is_oa and doi else None,
        "cited_by_count": 3,
        "openalex_id": "",
        "source_fetcher": source,
    }


def test_deduplicate_by_doi():
    """Two entries with same DOI should collapse to one."""
    papers = [
        _sample_paper("10.3390/f17050533", "Title A", "abstract", ["Author A"],
                     source="openalex"),
        _sample_paper("10.3390/F17050533", "Title A duplicate", "abstract2",
                     ["Author A"], source="crossref"),  # uppercase DOI
    ]
    deduped = deduplicate_papers(papers)
    assert len(deduped) == 1, f"expected 1 paper after dedupe, got {len(deduped)}"
    # Should prefer OpenAlex (priority 0 < CrossRef 1)
    assert deduped[0]["source_fetcher"] == "openalex"
    print("  ✓ test_deduplicate_by_doi")


def test_deduplicate_no_doi():
    """Entries without DOI should dedupe by (title, year)."""
    papers = [
        _sample_paper("", "Identical title here", "abs1", ["X"], source="rss"),
        _sample_paper("", "Identical title here", "abs2", ["X"], source="rss"),
    ]
    deduped = deduplicate_papers(papers)
    assert len(deduped) == 1
    print("  ✓ test_deduplicate_no_doi")


def test_scoring_high_priority_keyword():
    """Paper with 'urban forestry' (high priority +3) + 'urban tree' (+2) + Italy (+1)
       should score at least 6 + bonuses."""
    rules = {
        "areas": {
            "verde_urbano": {
                "positive_high": ["urban forestry"],
                "positive_medium": ["urban tree"],
                "positive_low": ["Italy"],
                "negative": [],
            }
        },
        "key_authors": [],
    }
    paper = _sample_paper(
        "10.1234/test1",
        "Urban forestry in Italy",
        "This paper studies urban tree species in Italy.",
        ["Anonymous Author"],
    )
    score, area, kws = score_paper(paper, rules)
    # +3 (urban forestry) +2 (urban tree) +1 (italy) +1 (OA bonus) = 7
    assert score == 7, f"expected score 7, got {score}: kws={kws}"
    assert area == "verde_urbano"
    print(f"  ✓ test_scoring_high_priority_keyword (score={score})")


def test_scoring_key_author_bonus():
    """Paper by Sjöman should get +5 author bonus."""
    rules = {
        "areas": {
            "verde_urbano": {
                "positive_high": ["urban tree species"],
                "positive_medium": [],
                "positive_low": [],
                "negative": [],
            }
        },
        "key_authors": [
            {"name": "Henrik Sjöman", "openalex_id": "A5017961344",
             "areas": ["verde_urbano"]}
        ],
    }
    paper = _sample_paper(
        "10.1234/test2",
        "Urban tree species selection",
        "Selection criteria.",
        ["Henrik Sjöman", "Other"],
    )
    score, area, kws = score_paper(paper, rules)
    # +3 (urban tree species) +1 (OA) +5 (Sjöman) = 9
    assert score == 9, f"expected score 9, got {score}: kws={kws}"
    assert any("author=Henrik" in kw for kw in kws), f"author bonus missing: {kws}"
    print(f"  ✓ test_scoring_key_author_bonus (score={score})")


def test_scoring_negative_keyword():
    """Negative keyword should subtract."""
    rules = {
        "areas": {
            "verde_urbano": {
                "positive_high": ["urban forestry"],
                "positive_medium": [],
                "positive_low": [],
                "negative": ["tropical rainforest"],
            }
        },
        "key_authors": [],
    }
    paper = _sample_paper(
        "10.1234/test3",
        "Urban forestry vs tropical rainforest comparison",
        "abstract here",
        ["Anon"],
    )
    score, _, _ = score_paper(paper, rules)
    # +3 - 2 + 1 (OA) = 2
    assert score == 2, f"expected score 2, got {score}"
    print(f"  ✓ test_scoring_negative_keyword (score={score})")


def test_seen_roundtrip():
    """Save and load seen DOIs."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "seen.json"
        original = {"10.1234/abc", "10.5678/def"}
        save_seen(path, original)
        loaded = load_seen(path)
        assert loaded == original, f"roundtrip failed: {loaded} != {original}"
        print("  ✓ test_seen_roundtrip")


def test_digest_writer_creates_file():
    """write_digest creates a markdown file with expected sections."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_digest.md"
        papers = [
            {**_sample_paper("10.3390/f17050533", "Important paper",
                            "Urban heat island study", ["Sjöman H."]),
             "score": 9, "area": "verde_urbano",
             "matched_keywords": ["+3:urban heat island", "+5:author=Sjöman"]},
        ]
        write_digest(path, papers, fetch_summary={"openalex_journal": 5},
                    threshold=5)
        content = path.read_text(encoding="utf-8")
        assert "# Letteratura — settimana" in content
        assert "Verde Urbano" in content
        assert "Important paper" in content
        assert "10.3390/f17050533" in content
        assert "⭐" in content  # score >= 8
        print(f"  ✓ test_digest_writer_creates_file ({len(content)} chars)")


def test_digest_writer_empty():
    """write_digest handles empty list gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty_digest.md"
        write_digest(path, [])
        content = path.read_text(encoding="utf-8")
        assert "Nessun paper sopra la soglia" in content
        print("  ✓ test_digest_writer_empty")


def test_config_files_valid_json():
    """sources.json and rules.json should be valid JSON with required keys."""
    repo_root = HERE.parent
    sources = json.loads((repo_root / "config" / "sources.json").read_text())
    assert "journals" in sources
    assert "authors" in sources
    assert "queries" in sources
    assert len(sources["journals"]) >= 1
    assert len(sources["authors"]) >= 1
    assert all("openalex_id" in j for j in sources["journals"]
               if not j.get("name", "").startswith("_"))
    print(f"  ✓ test_config_files_valid_json (journals={len(sources['journals'])}, "
          f"authors={len(sources['authors'])}, queries={len(sources['queries'])})")

    rules = json.loads((repo_root / "config" / "rules.json").read_text())
    assert "areas" in rules
    assert "key_authors" in rules
    assert "verde_urbano" in rules["areas"]
    assert "vta" in rules["areas"]
    print(f"  ✓ rules.json: {len(rules['areas'])} areas, "
          f"{len(rules['key_authors'])} key authors")


if __name__ == "__main__":
    print("=== Smoke test E2E monitor-letteratura-agronomo ===\n")
    tests = [
        test_deduplicate_by_doi,
        test_deduplicate_no_doi,
        test_scoring_high_priority_keyword,
        test_scoring_key_author_bonus,
        test_scoring_negative_keyword,
        test_seen_roundtrip,
        test_digest_writer_creates_file,
        test_digest_writer_empty,
        test_config_files_valid_json,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed.append(t.__name__)
        except Exception as e:
            print(f"  ✗ {t.__name__}: unexpected error: {e}")
            failed.append(t.__name__)

    print(f"\n=== {len(tests) - len(failed)}/{len(tests)} passed ===")
    sys.exit(1 if failed else 0)


# =====================================================================
# Test aggiunti il 15/09/2026 — patch al motore dopo il brief W38.
# Ogni test ricostruisce un caso REALE preso dai digest, non un caso di scuola.
# =====================================================================

from src.noise_filter import is_noise, is_preprint_or_repository, filter_noise

_RULES = json.loads((HERE.parent / "config" / "rules.json").read_text(encoding="utf-8"))


def test_falso_positivo_senza_keyword_forte_declassato():
    """Caso reale W38: transizione pascolo-foresta nelle Alpi italiane.

    Arrivava a 5 esatti con 'ecosystem services' + 'Italy' + 'Italian' + OA,
    senza una sola parola urbana.
    """
    p = _sample_paper(
        "10.1007/s11625-026-01889-7",
        "An integrated interdisciplinary framework to explore social-ecological "
        "implications of pasture-forest transition in the Italian Alps",
        "We study ecosystem services in Italy and the Italian Alps after pasture "
        "abandonment and spontaneous reforestation.",
        ["Andrea Scartazza", "Maria Adamo"],
        journal="Sustainability Science",
    )
    score, area, kws = score_paper(p, _RULES)
    assert score == 0, f"atteso declassamento a 0, ottenuto {score} ({kws})"
    assert any("declassato" in k for k in kws)
    print("  ✓ test_falso_positivo_senza_keyword_forte_declassato")


def test_paper_urbano_vero_resta_sopra_soglia():
    """Controprova: l'hit W38 score 11 deve restare, e ampiamente."""
    p = _sample_paper(
        "10.1016/j.ufug.2026.129679",
        "Educator perspectives on the evolving competencies of urban forestry education",
        "Urban forestry education and the ecosystem services delivered by the urban forest.",
        ["Sara Barron", "Cecil C. Konijnendijk"],
        journal="Urban forestry & urban greening",
    )
    p["author_ids"] = ["A5026003033"]
    score, area, kws = score_paper(p, _RULES)
    assert score >= 5, f"l'hit vero e stato scartato: {score} ({kws})"
    assert area == "verde_urbano"
    assert any("author=" in k for k in kws), "bonus autore per ID non applicato"
    print(f"  ✓ test_paper_urbano_vero_resta_sopra_soglia (score {score})")


def test_profilo_spezzato_konijnendijk_id_secondario():
    """Un lavoro sull'ID secondario deve dare lo stesso bonus del primario."""
    p = _sample_paper("10.1000/alt", "Urban forestry governance",
                      "urban greenspace and green infrastructure",
                      ["Cecil Konijnendijk van den Bosch"], journal="Forests")
    p["author_ids"] = ["A5008307501"]
    _, _, kws = score_paper(p, _RULES)
    assert any("author=" in k for k in kws), "ID alternativo non riconosciuto"
    print("  ✓ test_profilo_spezzato_konijnendijk_id_secondario")


def test_omonimo_ferrini_su_arxiv_non_prende_il_bonus():
    """Caso reale W19-W22: l'informatico dei Graph Neural Networks.

    Il paper non va scartato, ma senza il +5 non deve passare la soglia.
    """
    p = _sample_paper(
        "10.48550/arxiv.2608.00000",
        "Overcoming Shortcut Learning in Graph Neural Networks",
        "We propose a method for graph neural networks calibration.",
        ["Francesco Ferrini", "Veronica Lachi"],
        journal="arXiv (Cornell University)",
    )
    p["author_ids"] = ["A5048515755"]
    p["source_type"] = "repository"
    assert is_preprint_or_repository(p, _RULES)
    score, _, kws = score_paper(p, _RULES)
    assert any("author_bonus_negato" in k for k in kws)
    assert score < _RULES["min_score_threshold"], f"passa ancora la soglia: {score} ({kws})"
    print("  ✓ test_omonimo_ferrini_su_arxiv_non_prende_il_bonus")


def test_ferrini_vero_su_rivista_prende_il_bonus():
    """Controprova: lo stesso ID, su rivista peer-reviewed, resta valido."""
    p = _sample_paper(
        "10.1016/j.ufug.2026.11111",
        "Red-leafed trees under drought stress in the urban environment",
        "Urban tree physiology, street tree selection and ecosystem services.",
        ["Francesco Ferrini"],
        journal="Urban forestry & urban greening",
    )
    p["author_ids"] = ["A5048515755"]
    p["source_type"] = "journal"
    assert not is_preprint_or_repository(p, _RULES)
    _, _, kws = score_paper(p, _RULES)
    assert any("author=" in k for k in kws), "il Ferrini vero ha perso il bonus"
    print("  ✓ test_ferrini_vero_su_rivista_prende_il_bonus")


def test_omonimo_di_cognome_non_prende_piu_il_bonus():
    """Il match sul solo cognome faceva scattare +5 su qualunque omonimo.

    Caso concreto verificato il 15/09/2026 via API: 'F. Richard Hauer',
    ecologia fluviale, lavora NELLA STESSA universita del Richard J. Hauer
    dell'urban forestry.
    """
    p = _sample_paper("10.1000/fluvial", "Hydrology and sediment transport in gravel-bed rivers",
                      "Fish ecology and management in montane streams.",
                      ["F. Richard Hauer"], journal="Freshwater Biology")
    p["author_ids"] = ["A5076448658"]   # l'ecologo fluviale, non il nostro
    _, _, kws = score_paper(p, _RULES)
    assert not any("author=" in k for k in kws), f"bonus dato a un omonimo: {kws}"
    print("  ✓ test_omonimo_di_cognome_non_prende_piu_il_bonus")


def test_limite_noto_del_fallback_per_nome():
    """Documenta un limite che resta, invece di far finta che sia risolto.

    Senza author_ids (EuropePMC, CrossRef, RSS) due veri omonimi restano
    indistinguibili e il bonus scatta. E accettato: quelle fonti non
    espongono gli ID, e il caso e raro. Se un giorno mordera, la strada e
    incrociare la rivista, non il nome.
    """
    p = _sample_paper("10.1000/fluvial2", "Hydrology of gravel-bed rivers",
                      "Fish ecology in montane streams.",
                      ["Richard Hauer"], journal="Freshwater Biology")
    p.pop("author_ids", None)
    _, _, kws = score_paper(p, _RULES)
    assert any("author=" in k for k in kws), "il fallback per nome non funziona piu affatto"
    print("  ✓ test_limite_noto_del_fallback_per_nome (limite documentato, non risolto)")


def test_commento_di_open_review_scartato():
    """Caso reale W34-W36: la falla EGUsphere, 5 falsi hit dallo stesso preprint."""
    casi = [
        ({"title": "Reply on RC2", "doi": "10.5194/egusphere-2026-3814-ac1",
          "work_type": "peer-review"}, "work_type"),
        ({"title": "Comment on egusphere-2026-3814", "doi": "10.5194/egusphere-2026-3814-rc1",
          "work_type": "article"}, "title_prefix"),
        ({"title": "Urban tree growth", "doi": "10.5194/egusphere-2026-3814-sc2",
          "work_type": "article"}, "doi_pattern"),
    ]
    for stub, atteso in casi:
        noise, reason = is_noise(stub, _RULES)
        assert noise, f"non scartato: {stub}"
        assert atteso in reason, f"scartato per il motivo sbagliato: {reason}"
    # e un articolo vero non deve essere toccato
    ok = {"title": "Educator perspectives on urban forestry education",
          "doi": "10.1016/j.ufug.2026.129679", "work_type": "article"}
    assert not is_noise(ok, _RULES)[0]
    kept, dropped = filter_noise([c[0] for c in casi] + [ok], _RULES)
    assert len(kept) == 1 and len(dropped) == 3
    print("  ✓ test_commento_di_open_review_scartato")


def test_sources_e_rules_sono_sincronizzati():
    """Gli autori vivono in due file: se divergono, il motore lavora a meta."""
    cfg = HERE.parent / "config"
    sources = json.loads((cfg / "sources.json").read_text(encoding="utf-8"))
    rules = json.loads((cfg / "rules.json").read_text(encoding="utf-8"))
    ids_s = {a["openalex_id"] for a in sources["authors"]}
    ids_r = {a["openalex_id"] for a in rules["key_authors"]}
    assert ids_s == ids_r, f"disallineati: solo in sources {ids_s - ids_r}, solo in rules {ids_r - ids_s}"
    # nessun ID duplicato fra le riviste
    sids = [j["openalex_id"] for j in sources["journals"]]
    assert len(sids) == len(set(sids)), "rivista duplicata in sources.json"
    print(f"  ✓ test_sources_e_rules_sono_sincronizzati ({len(ids_s)} autori, {len(sids)} riviste)")

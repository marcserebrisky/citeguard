"""Parser tests — no network."""
from __future__ import annotations

from pathlib import Path

from citeguard.parse import (
    _HEADING_RE, clean_doi, looks_like_references, parse_bibtex,
    parse_references, parse_ris,
)


def test_clean_doi_variants():
    assert clean_doi("https://doi.org/10.1126/science.1225829") == "10.1126/science.1225829"
    assert clean_doi("doi:10.1038/nature14539.") == "10.1038/nature14539"
    assert clean_doi("see 10.1016/S0140-6736(97)11096-0)") == "10.1016/s0140-6736(97)11096-0"
    assert clean_doi("no doi here") is None


def test_parse_bibtex_fields():
    refs = parse_bibtex(Path(__file__).with_name("sample.bib").read_text())
    assert len(refs) == 6
    jinek = next(r for r in refs if r.key == "jinek2012crispr")
    assert jinek.doi == "10.1126/science.1225829"
    assert jinek.year == 2012
    assert "Jinek" in jinek.authors[0]
    book = next(r for r in refs if r.key == "cormen2009algorithms")
    assert book.entry_type == "book"
    assert book.is_grey_literature is True
    assert book.doi is None


def test_parse_freetext_extracts_doi_and_year():
    text = ("Doudna, J. (2020). A new era of genome editing. Nature, 578, 229. "
            "https://doi.org/10.1038/s41586-020-1978-5")
    refs = parse_references(text=text)
    assert len(refs) == 1
    assert refs[0].doi == "10.1038/s41586-020-1978-5"
    assert refs[0].year == 2020


def test_parse_numbered_list_splits():
    text = ("1. Alpha A. (2001). First paper. Journal A.\n"
            "2. Beta B. (2002). Second paper. Journal B.\n"
            "3. Gamma G. (2003). Third paper. Journal C.")
    refs = parse_references(text=text)
    assert len(refs) == 3
    assert refs[1].year == 2002


def test_parse_ris():
    ris = ("TY  - JOUR\nAU  - Doe, J\nTI  - A RIS Title\nPY  - 2019\n"
           "DO  - 10.1000/xyz123\nER  -\n")
    refs = parse_ris(ris)
    assert len(refs) == 1
    assert refs[0].doi == "10.1000/xyz123"
    assert refs[0].year == 2019
    assert refs[0].title == "A RIS Title"


def test_looks_like_references():
    assert looks_like_references("please verify these") is False
    assert looks_like_references("Smith J (2020). Some paper. doi:10.1000/xyz") is True
    assert looks_like_references("check my refs") is False


def test_numbered_wrapped_list_grouped_not_oversplit():
    # A numbered list copied from a PDF where entry 1 wraps onto a second line.
    text = ("1. Smith J, Doe A. Effects of X on Y. Nature.\n"
            "2020;12:34-56.\n"
            "2. Jones B. Another study. Science. 2019.")
    refs = parse_references(text=text)
    assert len(refs) == 2                      # not 3 — the wrap is folded in
    assert "2020;12:34-56" in refs[0].raw


def test_heading_regex_matches_variants_and_rejects_prose():
    for h in ["References", "References:", "REFERENCE LIST", "Bibliography",
              "Selected Bibliography", "7. Literature Cited", "Notes and References"]:
        assert _HEADING_RE.fullmatch(h), h
    for non in ["Introduction", "Methods and Materials",
                "We build on prior references in this work as discussed above"]:
        assert not _HEADING_RE.fullmatch(non), non


def test_bibtex_backfills_doi_from_url_field():
    bib = "@article{k, title={T}, author={A Author}, year={2020}, url={https://doi.org/10.1234/abc}}"
    refs = parse_bibtex(bib)
    assert refs[0].doi == "10.1234/abc"


def test_utf16_ris_decodes_and_parses():
    ris = "TY  - JOUR\nTI  - A UTF-16 Title\nPY  - 2019\nER  -\n"
    data = ris.encode("utf-16")  # includes a BOM, like EndNote/Notepad exports
    refs = parse_references(file_bytes=data, filename="refs.ris")
    assert len(refs) == 1
    assert refs[0].title == "A UTF-16 Title"

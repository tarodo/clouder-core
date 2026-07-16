from splitlab.facts_pass import FactsResult
from splitlab.merge import merge_passes
from splitlab.narrative_pass import NarrativeResult


def test_merge_unions_all_three_sources():
    narrative = NarrativeResult(narrative={"tagline": "t", "summary": "s", "confidence": 0.8})
    facts = FactsResult(
        facts={"founded_year": 2015, "catalog_size_estimate": None},
        profiles={"instagram_url": "https://www.instagram.com/x", "website": "https://x.com"},
        instagram_tier=2,
    )
    merged, prov = merge_passes(narrative, facts)
    assert merged["tagline"] == "t"
    assert merged["founded_year"] == 2015
    assert merged["instagram_url"] == "https://www.instagram.com/x"
    assert merged["catalog_size_estimate"] is None
    assert prov["tagline"] == "narrative"
    assert prov["founded_year"] == "facts_llm"
    assert prov["instagram_url"] == "profiles_tier2"
    assert prov["website"] == "profiles_regex"
    assert "catalog_size_estimate" not in prov  # null fields get no provenance


def test_facts_never_overwrite_narrative_keys():
    narrative = NarrativeResult(narrative={"notes": "narrative note"})
    facts = FactsResult(facts={"notes": "facts note"})
    merged, prov = merge_passes(narrative, facts)
    assert merged["notes"] == "narrative note"
    assert prov["notes"] == "narrative"


def test_null_profile_values_get_no_provenance():
    narrative = NarrativeResult(narrative={})
    facts = FactsResult(profiles={"website": None, "instagram_url": ""})
    merged, prov = merge_passes(narrative, facts)
    assert merged["website"] is None
    assert "website" not in prov
    assert "instagram_url" not in prov


def test_profiles_never_overwrite_narrative():
    narrative = NarrativeResult(narrative={"summary": "real summary"})
    facts = FactsResult(profiles={"summary": "https://bogus.example"})
    merged, prov = merge_passes(narrative, facts)
    assert merged["summary"] == "real summary"
    assert prov["summary"] == "narrative"

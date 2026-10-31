from phase3_final.seo_snippet_agent import DeterministicSeoSnippetAgent


def test_deterministic_snippet_uses_exact_part_number_once_in_title():
    agent = DeterministicSeoSnippetAgent()
    result, _ = agent.generate(part_number="2N7000", category_key="mosfet")
    assert result["seo_title"].count("2N7000") == 1
    assert "2N7000" in result["meta_description"]


def test_deterministic_snippet_uses_only_verified_manufacturer_when_present():
    agent = DeterministicSeoSnippetAgent()
    result, _ = agent.generate(
        part_number="TC427CPA",
        category_key="ic",
        manufacturer="Microchip",
    )
    assert "Microchip" in result["meta_description"]
    assert "TC427CPA" in result["seo_title"]

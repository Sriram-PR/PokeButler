import pytest

from utils.matching import get_close_matches_async


@pytest.mark.asyncio
async def test_fuzzy_matching_exact():
    options = ["garchomp", "pikachu", "charizard"]
    matches = await get_close_matches_async("garchomp", options)
    assert matches[0] == "garchomp"


@pytest.mark.asyncio
async def test_fuzzy_matching_typo():
    options = ["garchomp", "pikachu", "charizard"]
    # Typo: "garchompp" -> "garchomp"
    matches = await get_close_matches_async("garchompp", options)
    assert "garchomp" in matches


@pytest.mark.asyncio
async def test_fuzzy_matching_empty():
    matches = await get_close_matches_async("garchomp", [])
    assert matches == []


@pytest.mark.asyncio
async def test_fuzzy_matching_no_match():
    options = ["pikachu", "bulbasaur"]
    # "Digimon" is too different from options
    matches = await get_close_matches_async("digimon", options, cutoff=0.9)
    assert matches == []

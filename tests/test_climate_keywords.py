import pytest

from app.handlers.climate import is_keyword


@pytest.mark.parametrize(
    "text",
    ["душно", "Душно!", "душно??", "  ДУШНО.  ", "душно 🥵", "Климат", "климат?", "душновато", "душно-то как", "как душно", "душно в офисе"],
)
def test_keyword_matches(text):
    assert is_keyword(text)


@pytest.mark.parametrize("text", ["тут не душно", "климат-контроль сломан", "", "🥵", "привет"])
def test_keyword_ignores_other_text(text):
    assert not is_keyword(text)

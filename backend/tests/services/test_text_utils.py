from services.text_utils import truncate_text


def test_returns_text_unchanged_when_under_the_limit():
    assert truncate_text("short text", 100, "[cut]") == "short text"


def test_cuts_at_the_last_newline_within_the_limit():
    text = "first line\nsecond line is quite long here"
    result = truncate_text(text, 15, "[cut]")

    assert result == "first line[cut]"


def test_cuts_at_the_last_space_when_no_newline_available():
    text = "one two three four five"
    result = truncate_text(text, 13, "[cut]")

    assert result == "one two[cut]"


def test_hard_cuts_when_no_boundary_exists_within_the_limit():
    text = "a" * 50
    result = truncate_text(text, 10, "[cut]")

    assert result == "a" * 10 + "[cut]"


def test_exact_length_boundary_is_not_truncated():
    assert truncate_text("12345", 5, "[cut]") == "12345"

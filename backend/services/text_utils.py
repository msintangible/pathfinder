def truncate_text(text: str, max_chars: int, marker: str) -> str:
    """
    Trim text to max_chars, cutting at the last newline or space so a word
    isn't split mid-token, then appending marker so the model (and anyone
    reading logs) knows the text was cut short rather than genuinely ending
    there.
    """
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n", 0, max_chars)
    if cut == -1:
        cut = text.rfind(" ", 0, max_chars)
    if cut == -1:
        cut = max_chars
    return text[:cut] + marker

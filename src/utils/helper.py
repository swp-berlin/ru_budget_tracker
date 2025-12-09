"""
Miscellaneous utility functions
"""


def add_breaks(string: str, interval: int = 30) -> str:
    """
    Insert <br> into a string at specified intervals, for better readability.
    Breaks are added at the next after the end of the interval.
    Args:
        string (str): The input string to modify.
        interval (int): The interval at which to insert line breaks.
    Returns:
        str: The modified string with <br> inserted.
    """
    if len(string) <= interval:
        return string

    parts = []
    start = 0
    while start < len(string):
        end = start + interval
        if end >= len(string):
            parts.append(string[start:])
            break
        # Find the next space to avoid breaking words
        space_index = string.find(" ", end)
        if space_index == -1:
            parts.append(string[start:])
            break
        parts.append(string[start:space_index])
        start = space_index + 1
    return "<br>".join(parts)

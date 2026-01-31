"""
Miscellaneous utility functions
"""


def add_breaks(string: str, interval: int = 30, tolerance: int = 5) -> str:
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
        # Find the next best space to break
        # If there is a space in a 10 character window centered at end, break there
        # otherwise break at next space after end
        space_index = string.rfind(" ", end - tolerance, end + tolerance)
        if space_index == -1 or space_index <= start:
            space_index = string.find(" ", end)
            if space_index == -1:
                parts.append(string[start:])
                break
        parts.append(string[start:space_index])
        start = space_index + 1
    return "<br>".join(parts)

"""Turning stored character offsets into marked-up sentence text."""
import html
import re

# The miRNA side of an evidence row is stored short. `mir_regex.syn` matches only
# the stem, so 743,345 of ~794k stored miRNA spans are exactly three characters
# ('miR'); the digits that identify the miRNA live in a `suffix` field that never
# reaches the database (analysis.py builds entity_positions as
# start_position + hit_length). Highlighting the stored span alone renders
# "**miR**-26b-5p". Extending rightward over the name characters that follow
# recovers the real surface form from the sentence text itself.
#
# Known limitation: in an enumeration such as "miR-21, 221 and 16" three
# normalized ids share the single "miR" span, so all three extend to "miR-21".
# The correct fix is threading `suffix` through CoOccurence -> .cooc -> loader,
# which needs a re-extraction.
# A dot is only part of the name when a word character follows it ("miR-1.2");
# a trailing dot is sentence punctuation and must not be highlighted.
_NAME_TAIL = re.compile(r"(?:[-\w*]|\.(?=\w))*")


def extend_mirna_span(text: str, start: int, end: int) -> tuple[int, int]:
    if not 0 <= start < end <= len(text):
        return start, end
    return start, end + _NAME_TAIL.match(text, end).end() - end


def render(text: str, spans: list[tuple[int, int, str]]) -> str:
    """HTML for `text` with each (start, end, css_class) span wrapped in <mark>.

    Overlapping spans are merged into the earlier one's class rather than
    producing nested tags; spans arrive from independent hits and may collide.
    """
    ordered = sorted({(s, e, k) for s, e, k in spans if 0 <= s < e <= len(text)})
    out, cursor = [], 0
    for start, end, kind in ordered:
        if start < cursor:
            continue
        out.append(html.escape(text[cursor:start]))
        out.append(f'<mark class="{kind}">{html.escape(text[start:end])}</mark>')
        cursor = end
    out.append(html.escape(text[cursor:]))
    return "".join(out)

"""status_text.py -- text access for the status extractor: prose sentences and official status tables.

Prose is taken with tables removed and block tags turned into line breaks, so a sentence never runs across a list
item, heading or table row. Official tables are read cell by cell under their own headers; a row whose cell count
does not match its headers is counted and reported, never silently dropped.
"""
import html
import re

BLOCK = re.compile(r"</?(p|li|h[1-6]|div|br|ul|ol|section|article|header|footer|blockquote|tr)\b[^>]*>", re.I)
TABLE = re.compile(r"<table.*?</table>", re.S | re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
POSITION_PREFIX = re.compile(r"^[A-Z]{1,3}\s+")


def cell_text(fragment):
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text).replace("\xa0", " ")).strip()


def prose_lines(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    page = TABLE.sub("\n", page)
    page = BLOCK.sub("\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page).replace("\xa0", " ").replace("’", "'").replace("‘", "'")
    return [re.sub(r"\s+", " ", line).strip() for line in page.split("\n") if line.strip()]


def sentences(page):
    out = []
    for line in prose_lines(page):
        out.extend(part for part in SENTENCE_END.split(line) if part)
    return out


def status_tables(page):
    """Rows of every table whose headers include Player and a status column, as header->cell dicts.

    Returns (rows, malformed). A malformed row has a cell count that differs from its table's headers.
    """
    rows, malformed = [], 0
    for tbl in TABLE.findall(page):
        heads = [cell_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", tbl, re.S | re.I)]
        lowered = [h.lower() for h in heads]
        if "player" not in lowered or not any(h == "status" or h.startswith("game status") for h in lowered):
            continue
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S | re.I):
            cells = [cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
            if not cells:
                continue
            if len(cells) != len(heads):
                malformed += 1
                continue
            rows.append(dict(zip(heads, cells)))
    return rows, malformed


def table_player(cell):
    return POSITION_PREFIX.sub("", cell).strip()


def status_column(row):
    for head, value in row.items():
        if head.lower() == "status" or head.lower().startswith("game status"):
            return value
    return ""

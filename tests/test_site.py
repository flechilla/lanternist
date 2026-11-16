"""The public site (site/) is static, so it carries its own copy of a few of the app's facts to time
Luna's film. These tests keep the copies in step with the app."""

import re
from pathlib import Path

from lanternist import storyboard, text, writer

PUBLIC = Path(__file__).parent.parent / "site" / "public"
STORY = (PUBLIC / "story.js").read_text()


def _object(name: str) -> dict[str, str]:
    body = re.search(rf"export const {name} = \{{(.*?)\}};", STORY, re.DOTALL)
    assert body, f"story.js has no {name}"
    return dict(re.findall(r"(\w+): \"?([^\",\n]+)\"?,", body.group(1)))


def test_the_site_reads_at_the_writers_speeds() -> None:
    assert {k: int(v) for k, v in _object("WPM").items()} == writer.WPM


def test_the_site_offers_the_apps_languages() -> None:
    assert list(_object("LANGUAGES")) == list(text.LANGUAGES)


def test_the_site_rerolls_like_the_app() -> None:
    assert f"export const SEED = {storyboard.Storyboard.model_fields['seed'].default};" in STORY
    found = re.search(r"nextSeed = \(seed\) => \(seed \* (\d+) \+ (\d+)\) % (\d+);", STORY)
    assert found
    a, b, m = map(int, found.groups())
    assert all((s * a + b) % m == storyboard.next_seed(s) for s in (7, 8, 104_729))


def test_the_studio_paints_the_apps_styles() -> None:
    rooms = (PUBLIC / "studio" / "rooms.js").read_text()
    body = re.search(r"export const STYLES = \[(.*?)\];", rooms, re.DOTALL)
    assert body, "rooms.js has no STYLES"
    assert re.findall(r'\["(\w+)",', body.group(1)) == list(writer.STYLES)


def test_every_style_has_its_cast_sheets() -> None:
    img = PUBLIC / "studio" / "img"
    assert all((img / f"cast-{style}-{take}.webp").is_file() for style in writer.STYLES for take in (0, 1))


def test_the_brick_page_offers_the_apps_choices() -> None:
    page = (PUBLIC / "bricks" / "index.html").read_text()
    styles = re.search(r'<ul class="styles"[^>]*>(.*?)</ul>', page, re.DOTALL)
    assert styles, "the brick page lists no picture styles"
    assert len(re.findall(r"<li>", styles.group(1))) == len(writer.STYLES)
    picks = re.search(r'<dl class="picks">(.*?)</dl>', page, re.DOTALL)
    assert picks, "the brick page lists no audiences or kinds"
    lists = re.findall(r"<dd>(.*?)</dd>", picks.group(1), re.DOTALL)
    audiences, kinds = (re.findall(r"<(?:span|b)>", dd) for dd in lists)
    assert (len(audiences), len(kinds)) == (len(writer.AUDIENCES), len(writer.KINDS))


def test_the_brick_page_reads_its_first_line_in_every_language() -> None:
    tale = (PUBLIC / "bricks" / "tale.js").read_text()
    body = re.search(r"export const FIRST_LINE = \{(.*?)\n\};", tale, re.DOTALL)
    assert body, "tale.js has no FIRST_LINE"
    assert re.findall(r"^  (\w+):", body.group(1), re.MULTILINE) == list(text.LANGUAGES)

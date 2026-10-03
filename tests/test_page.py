"""Static gates for web/index.html. Run: python3 tests/test_page.py

The canvas renderer carries more logic than the sim does now (label placement,
occlusion, adaptive zoom), and none of it is reachable from the Python suite.
A 200 from the server proves nothing about the page, so this checks the two
things that actually break it: a syntax error in the extracted script, and a
getElementById target that does not exist in the markup.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "..", "web", "index.html")

PASS = []


def check(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {name}: {type(e).__name__}: {e}")
        return False
    print(f"ok   {name}")
    PASS.append(name)
    return True


def load():
    with open(WEB, encoding="utf-8") as f:
        return f.read()


def script_and_markup():
    html = load()
    if "<script>" not in html or "</script>" not in html:
        raise AssertionError("no <script> block found")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    return html, script


def test_script_parses():
    """node --check on the extracted script: catches the missing-operator class
    of bug that renders as a blank canvas with no error in the console."""
    node = shutil.which("node")
    if not node:
        print("     (node unavailable, skipping)")
        return
    _html, script = script_and_markup()
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr.strip()[:400]
    finally:
        os.unlink(path)


def test_element_ids_exist():
    """Every id the script reaches for must exist in the markup, or the widget
    is silently dead."""
    html, script = script_and_markup()
    declared = set(re.findall(r'\bid="([^"]+)"', html))
    # ids created at runtime by template literals are not markup ids
    runtime = set(re.findall(r'id="\$\{[^}]+\}"', html))
    referenced = set(re.findall(r'getElementById\("([^"]+)"\)', script))
    missing = sorted(referenced - declared)
    assert not missing, f"getElementById targets missing from markup: {missing}"


def test_labels_go_through_one_placement_pass():
    """Regression guard: each subsystem used to draw its own fixed-size text,
    which stacked four labels on one point in Tern's system."""
    _html, script = script_and_markup()
    for fn in ("function placeLabels(", "function drawLabels(", "function labelFontPx(",
               "function labelBox(", "const boxHits", "function shortLocName("):
        assert fn in script, f"missing label plumbing: {fn}"
    # No fixed-size label text left in the canvas draw path.
    for pattern in (r'ctx\.font = "11px sans-serif"', r'ctx\.font = "10px sans-serif"',
                    r'ctx\.font = "bold 11px sans-serif"'):
        assert not re.search(pattern, script), f"fixed-size label font remains: {pattern}"
    # The canvas must not draw text directly outside the shared pass.
    direct = re.findall(r'ctx\.fillText\((?!cand\.text)', script)
    # one for the empty-state hint, one for the frame readout, one in drawLabels
    assert len(direct) <= 3, f"labels drawn outside the shared pass: {len(direct)} call sites"


def test_label_halo_does_not_bloom():
    """The halo separates text from orbit rings. Stroking it in the light ink
    colour at 2.5px on an 8px font filled the glyph counters and made labels
    unreadable -- it must be dark and proportional to the type size."""
    _html, script = script_and_markup()
    halo = re.search(r"if\(cand\.halo\)\{(.*?)\n    \}", script, re.S)
    assert halo, "label halo block not found"
    block = halo.group(1)
    assert "THEMES[themeName].bg" in block, "halo must use the theme background, not ink"
    assert "ctx.strokeStyle = tint(THEMES[themeName].ink" not in script, \
        "light halo reintroduced; it blooms the type"
    assert re.search(r"lineWidth = Math\.max\(1, cand\.h \* 0\.\d+\)", block), \
        "halo width must scale with font size, not be fixed"


def test_zoom_is_adaptive_and_bounded():
    """The helio view and a moon system are ~3200x apart; a constant wheel rate
    needed ~81 notches to cross that, and an earlier level-snapping rate was
    jerky (2.3x jumps then a 0.7% dead notch).

    Zoom must also go MUCH deeper than "fit the system". The planet's drawn disc
    is 1/PLANET_DISC_DIV of the outermost ring, so filling the screen with a
    planet needs ~250000x, and the disc cap used to be 60px -- which made
    everything past the system fit a no-op: the planet stopped growing while the
    rings slid off screen.
    """
    _html, script = script_and_markup()
    assert "function wheelZoomStep(" in script, "missing wheel zoom plumbing"
    assert "nextZoomLevel" not in script, "level-snapping zoom returned; it was jerky"
    assert "applyWheelZoom" not in script, "snap-to-level zoom returned; it was jerky"

    max_zoom = int(re.search(r"const MAX_ZOOM = (\d+)", script).group(1))
    assert max_zoom >= 100000, (
        f"MAX_ZOOM {max_zoom} cannot reach a screen-filling planet; the disc is "
        f"1/PLANET_DISC_DIV of the outermost ring")
    disc_div = int(re.search(r"const PLANET_DISC_DIV = (\d+)", script).group(1))
    disc_cap = int(re.search(r"const MAX_DISC_PX = (\d+)", script).group(1))
    assert disc_cap >= 2000, f"disc cap {disc_cap}px clips planets before MAX_ZOOM"

    sys.path.insert(0, os.path.join(HERE, ".."))
    from sim.state import build_sol
    bodies = build_sol().bodies
    base_scale = (680 / 2) / (15.0 * 1.05)

    deepest = None
    for planet in (b for b in bodies.values() if not b.parent):
        extent = max((b.a for b in bodies.values() if b.parent == planet.id), default=0.0)
        if extent <= 0:
            continue
        disc = extent * base_scale * max_zoom / disc_div
        if deepest is None or disc > deepest[1]:
            deepest = (planet.id, disc)
    assert deepest, "no mooned systems in the fixture"
    assert deepest[1] >= 300, (
        f"{deepest[0]} disc only reaches {deepest[1]:.0f}px at MAX_ZOOM; zooming in "
        f"still shows nothing to inspect")


def test_start_here_is_a_dialog_not_a_sidebar_card():
    """The static START HERE card became a real tutorial dialog with steps."""
    html, script = script_and_markup()
    assert 'id="p-guide"' not in html, "START HERE sidebar card is back"
    assert 'id="section-tutorial"' in html, "tutorial dialog section missing"
    assert 'id="p-tutorial"' in html, "tutorial panel missing"
    assert "const TUTORIAL = [" in script, "tutorial steps missing"
    for fn in ("function tutorialPanel()", "function wireTutorial(", "function tutorialDone()"):
        assert fn in script, f"missing tutorial plumbing: {fn}"
    steps = re.search(r"const TUTORIAL = \[(.*?)\n\];", script, re.S)
    assert steps and steps.group(1).count('id:"') >= 5, "tutorial needs real steps"


def test_selection_card_has_a_schematic():
    """'What have I selected' draws a diagram of the thing, not just text."""
    html, script = script_and_markup()
    assert 'id="sel-viz"' in html, "selection schematic canvas missing"
    for fn in ("function drawSelectionViz(", "function vizShip(", "function vizGate("):
        assert fn in script, f"missing schematic renderer: {fn}"
    assert "sel.focus" in script, "schematic does not follow the selection"
    assert "drawSelectionViz()" in script, "schematic is never drawn"


def test_detached_labels_get_leaders():
    """A label pushed off its marker must show a leader, or a crowded chart
    reads as names floating near the wrong thing."""
    _html, script = script_and_markup()
    assert "const LEADER_PX" in script, "LEADER_PX threshold missing"
    assert "function boxGap(" in script, "boxGap missing"
    assert "boxGap(box, cand.x, cand.y)" in script, "leader distance not measured"
    # Threshold must be relative to the marker radius: a label hugging a 335px
    # planet disc is ~348px from its centre and is correctly placed there.
    assert "gap > cand.r + LEADER_PX" in script, \
        "leader threshold must be measured past the marker radius, not absolutely"
    slots = re.search(r"const LABEL_SLOTS = \[(.*?)\];", script, re.S).group(1)
    # Each slot carries a ring number; ring 1 hugs the marker, ring 2 is pushed
    # out far enough that it needs a leader.
    assert slots.count(", 1]") >= 8, f"expected a tight first ring, got {slots.count(', 1]')}"
    assert slots.count(", 2]") >= 6, f"expected a second, further-out ring, got {slots.count(', 2]')}"


def test_markers_scale_below_their_world():
    """A station marker larger than the planet it marks made every system look
    wrong at depth."""
    _html, script = script_and_markup()
    for fn in ("function stationMarkerR(", "function shipGlyphR(", "function sunDisplayRadius("):
        assert fn in script, f"missing marker scaling: {fn}"
    # sqrt(view.zoom) markers are what produced 10px squares on a 9px orbit.
    assert "Math.sqrt(view.zoom)" not in script, "sqrt(zoom) marker sizing remains"
    assert "Math.max(12, markerR" not in script, "old marker clamp remains"


def test_canvas_matches_display_resolution():
    """The backing store was 860x680 on a 1401px-wide element, so every frame
    was upscaled ~1.6x and looked soft when zoomed."""
    _html, script = script_and_markup()
    assert "function fitCanvas()" in script, "fitCanvas missing"
    assert "devicePixelRatio" in script, "devicePixelRatio not honoured"
    assert "ctx.setTransform(PX, 0, 0, PX, 0, 0)" in script, "PX transform not applied in draw()"


if __name__ == "__main__":
    tests = [
        ("script_parses", test_script_parses),
        ("element_ids_exist", test_element_ids_exist),
        ("labels_single_pass", test_labels_go_through_one_placement_pass),
        ("label_halo_clean", test_label_halo_does_not_bloom),
        ("zoom_adaptive_bounded", test_zoom_is_adaptive_and_bounded),
        ("tutorial_dialog", test_start_here_is_a_dialog_not_a_sidebar_card),
        ("selection_schematic", test_selection_card_has_a_schematic),
        ("label_leaders", test_detached_labels_get_leaders),
        ("markers_scale", test_markers_scale_below_their_world),
        ("canvas_resolution", test_canvas_matches_display_resolution),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)
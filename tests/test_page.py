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
    needed ~81 notches to cross that, and MAX_ZOOM used to allow zooming to a
    state where the outer ring had run off canvas.

    The guarantee to hold: the DEEPEST mooned system (the one needing the
    largest fit zoom) must be both reachable and still entirely on canvas at
    full zoom. Shallower systems may be zoomed past -- that is ordinary map
    behaviour -- but the deepest one can never be zoomed into a broken view.
    """
    _html, script = script_and_markup()
    assert "function wheelZoomStep(" in script, "missing wheel zoom plumbing"
    # The level-snapping version was jerky (2.3x jumps then a 0.7% dead notch);
    # the rate must be a smooth monotonic function of zoom, with no snapping.
    assert "nextZoomLevel" not in script, "level-snapping zoom returned; it was jerky"
    assert "applyWheelZoom" not in script, "snap-to-level zoom returned; it was jerky"
    m = re.search(r"const MAX_ZOOM = (\d+)", script)
    assert m, "MAX_ZOOM not found"
    max_zoom = int(m.group(1))

    sys.path.insert(0, os.path.join(HERE, ".."))
    from sim.state import build_sol
    bodies = build_sol().bodies
    half_canvas = 680 / 2          # canvas logical height
    fill = 0.38                    # systemZoomFor fills 38% of the short edge
    base_scale = half_canvas / (15.0 * 1.05)   # fitBaseScale: min(W,H)/2 / outer body

    systems = {}
    for planet in (b for b in bodies.values() if not b.parent):
        extent = max((b.a for b in bodies.values() if b.parent == planet.id), default=0.0)
        if extent > 0:
            systems[planet.id] = (extent, fill * 2 * half_canvas / (extent * base_scale))
    assert systems, "no mooned systems found in the fixture"

    deepest_id = max(systems, key=lambda k: systems[k][1])
    extent, fit = systems[deepest_id]
    assert fit <= max_zoom, (
        f"{deepest_id} needs {fit:.0f}x to fit but MAX_ZOOM is {max_zoom}: its system "
        f"can never be fully framed")
    ring_at_max = extent * base_scale * max_zoom
    assert ring_at_max <= half_canvas + 4, (
        f"at MAX_ZOOM the {deepest_id} system outer ring is {ring_at_max:.0f}px against a "
        f"{half_canvas:.0f}px half-canvas: zooming in breaks the view")


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
        ("markers_scale", test_markers_scale_below_their_world),
        ("canvas_resolution", test_canvas_matches_display_resolution),
    ]
    ok = all(check(n, f) for n, f in tests)
    print(f"\n{len(PASS)}/{len(tests)} passed")
    sys.exit(0 if ok else 1)
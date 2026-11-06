# CLAUDE.md

Usage, CLI options and output formats are documented in `README.md`. This file covers how
the code is organised, why it is built this way, and how to extend it.

## Layout

```
src/geo_points_view/
  cli.py       argparse, orchestration, output folders, diagram copy, console summary
  analysis.py  dataclasses (Observer, Target, Sample, Zones, Obstacle, Case, Result),
               profile building, visibility analysis, top-obstacle list
  dem.py       CogTile (minimal GeoTIFF reader), Terrain (tile download, cache, lookup, peak search)
  geodesy.py   sphere maths: distance, bearing, great circle, tangent-plane frame, ray height
  render.py    SVG diagram, PNG through headless Chrome
  i18n.py      every user-facing string, per language
tests/
  _tiff.py     writer for synthetic Copernicus-style tiles (the inverse of CogTile)
  test_*.py    unittest-style tests, runnable with pytest or `python -m unittest`
diagrams/      committed final SVGs, one per point pair (binary in .gitattributes)
output/        per-run results, git-ignored
```

Data flows one way: `cli` → `Terrain` + `analysis.run` → `Result` → JSON/CSV writers and
`render.draw_svg`. Analysis code never prints or touches files. Rendering never
re-computes visibility; it reads the `Case` objects.

## Decisions

- **Standard library only at runtime.** GDAL/rasterio/numpy were not available where the
  project started, and the tool should install with a bare `pip install`. `CogTile` reads
  only what Copernicus tiles use: little-endian classic TIFF, tiled, float32, DEFLATE, and
  predictor 1 or 3. Anything else raises instead of returning wrong heights. If numpy ever
  becomes a dependency, keep the `Terrain.height/peak` interface and swap the internals.
- **GLO-30 first, GLO-90 fallback.** Some 30 m tiles are not published (N41E044, around
  Tbilisi, is one). Both 403 and 404 mean "no such tile". That is cached as a `.missing`
  marker file so the cache works offline. A tile missing from both sources is treated as
  sea level (0 m).
- **Tangent-plane frame with effective radius.** Refraction is modelled by Earth radius
  `R/(1-k)`. In that frame, rays are straight lines from the observer. That is why
  `geodesy.elevation_angle` and `ray_height` are exact inverses, and why the diagram can
  draw rays as straight lines and altitude lines as curves. Keep all three
  (analysis, diagram, tests) on the same `tangent_xy` function.
- **Zones instead of smarter obstacle detection.** The DEM is a surface model, so the
  observer's surroundings (`near_skip`) and the target's own cone (`summit_zone`) would
  produce false blockers. `massif_zone` splits "can the summit be seen at all" from "how
  much rises above the foreground". The two answers are reported separately on purpose:
  the first is usually dominated by the mountain's own shoulder.
- **Two sampling modes.** `bilinear` is the estimate and `max4` is the pessimistic bound.
  Every case is computed for both, plus refraction coefficients 0, 0.13 and 0.20
  (`cli.REFRACTION_CASES`) and the user's `--k`.
- **Outputs.** Every run gets a fresh timestamped folder, so nothing is overwritten.
  `diagrams/<a>-<b>.svg` is the one curated artefact and is overwritten per pair. File
  names go through `cli.slug`, which transliterates Cyrillic, so committed names stay
  ASCII.
- **PNG through Chrome** rather than cairosvg etc.: it needs no Python dependency, and
  Chrome renders the SVG exactly as a browser shows it. The renderer is optional and
  skipped with a warning when no browser is found.
- **English by default**, `--lang` switches the diagram and the summary. JSON/CSV keys are
  always English.

## Extending

- **New language:** add a dict to `i18n.TEXT` with every key of the `en` entry, plus an
  entry in `i18n.HEIGHT_SOURCE`. `--lang` choices come from `TEXT` automatically, and the
  slug transliteration in `cli._TRANSLIT` may need the new alphabet too.
- **New DEM source:** add a `(label, base_url, arcsec)` row to `Terrain.SOURCES` if it uses
  the same naming and TIFF layout. Otherwise subclass or replace `Terrain`; analysis only
  needs `height(lat, lon, pessimistic)`, `peak(...)` and `tiles` (each with `label` and
  `path`). Don't loosen the format checks in `CogTile._read_ifd`.
- **New analysis output** (e.g. horizon panorama, several targets): add a function in
  `analysis.py` that takes the profile and points and returns dataclasses. Attach the
  result to `Result` so it lands in `result.json` via `asdict` with no extra serialisation
  code.
- **New CLI option:** add it in `build_parser` under the right argument group and add a
  row to the matching README table. If it changes results, add it to the `parameters`
  block in `write_outputs` so the run stays reproducible from `result.json`.
- **Diagram changes:** everything visual is in `render.draw_svg`. Text goes through `tr()`
  and `escape()`. Coordinates come from `tangent_xy` so rays stay straight. Check both a
  short (~100 km) and a long (~200 km) route: the y-range, grid step and km tick spacing
  adapt to both.

## Testing

- `pytest`, or `PYTHONPATH=src python3 -m unittest` without the dev extras.
  `python3 -W error::ResourceWarning -m unittest` also catches unclosed tile files.
- Tests must not hit the network. Build terrain with `tests/_tiff.write_tile` and pass
  `--cache-dir` (see `test_cli.EndToEndTest`). A `.missing` marker forces the GLO-90 path.
- Synthetic terrain is coarse. Keep `--summit-zone` wide enough that pixels next to the
  summit are not counted as blockers.
- A real-data regression check: Mtatsminda → Kazbek (README example) must give "visible",
  ≈1043 m above the foreground (3273 m point at 93.3 km) for k = 0.13 bilinear.

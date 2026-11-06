"""User-facing strings for the diagram and the console summary. Add a language by adding a dict."""
from __future__ import annotations

TEXT: dict[str, dict[str, str]] = {
    'en': {
        # diagram
        'ray_target': 'ray to the summit of {b}',
        'ray_foreground': 'ray over the highest foreground obstacle (more than {z} km from the target)',
        'ray_blocker': 'ray over the obstacle hiding the target',
        'grid': 'altitude lines follow the Earth curvature (k = {k})',
        'sea_level': 'sea level',
        'x_axis': 'distance from the observer ({a}), km  ·  vertical exaggeration ×{ex}',
        'm': 'm', 'km': 'km',
        'verdict_visible': '{b} is visible: ≈{v:.0f} m rises above the foreground',
        'verdict_hidden': '{b} is hidden by a {h:.0f} m point at {d:.1f} km',
        # console summary
        'observer': 'Observer', 'target': 'Target',
        'ground': 'ground {g:.0f} m + eye {e:.1f} m',
        'distance': 'Distance {d:.1f} km, bearing {b:.1f}°',
        'dem': 'DEM tiles',
        'col_k': 'k', 'col_dem': 'DEM', 'col_vis': 'visible', 'col_angle': 'angle',
        'col_blocker': 'highest point on the route', 'col_top': 'visible top',
        'col_fg': 'above foreground',
        'yes': 'YES', 'no': 'NO',
        'top': 'Highest-angle points (k = {k}); clearance = how far below the ray to the summit:',
        'clearance': 'clearance',
        'written': 'Results written to {d}',
        'diagram': 'Diagram copied to {p}',
        'png_skipped': 'PNG skipped: no Chrome/Chromium found (use --browser)',
    },
    'ru': {
        'ray_target': 'луч на вершину: {b}',
        'ray_foreground': 'луч через самое высокое препятствие переднего плана (дальше {z} км от цели)',
        'ray_blocker': 'луч через препятствие, закрывающее цель',
        'grid': 'линии высот изогнуты по кривизне Земли (k = {k})',
        'sea_level': 'уровень моря',
        'x_axis': 'расстояние от наблюдателя ({a}), км  ·  вертикальный масштаб ×{ex}',
        'm': 'м', 'km': 'км',
        'verdict_visible': '{b} виден: над передним планом поднимается ≈{v:.0f} м',
        'verdict_hidden': '{b} не виден: закрывает точка {h:.0f} м на {d:.1f} км',
        'observer': 'Наблюдатель', 'target': 'Цель',
        'ground': 'земля {g:.0f} м + глаза {e:.1f} м',
        'distance': 'Расстояние {d:.1f} км, азимут {b:.1f}°',
        'dem': 'Тайлы DEM',
        'col_k': 'k', 'col_dem': 'DEM', 'col_vis': 'видно', 'col_angle': 'угол',
        'col_blocker': 'самая высокая точка на пути', 'col_top': 'видимая часть',
        'col_fg': 'над передним планом',
        'yes': 'ДА', 'no': 'НЕТ',
        'top': 'Точки с наибольшим углом (k = {k}); запас = насколько ниже луча на вершину:',
        'clearance': 'запас',
        'written': 'Результаты записаны в {d}',
        'diagram': 'Диаграмма скопирована в {p}',
        'png_skipped': 'PNG не создан: Chrome/Chromium не найден (см. --browser)',
    },
}

HEIGHT_SOURCE = {
    'en': {'dem': 'DEM', 'dem-peak': 'highest DEM pixel', 'override': 'given'},
    'ru': {'dem': 'DEM', 'dem-peak': 'высшая точка DEM', 'override': 'задано'},
}

LANGUAGES = tuple(TEXT)


def tr(lang: str, key: str, **kw) -> str:
    return TEXT[lang][key].format(**kw)

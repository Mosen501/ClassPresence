from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components


_COMPONENT_PATH = Path(__file__).resolve().parent / "frontend" / "geo_capture"
_geo_capture = components.declare_component("geo_capture", path=str(_COMPONENT_PATH))
_LOCATION_PICKER_PATH = Path(__file__).resolve().parent / "frontend" / "location_picker"
_location_picker = components.declare_component(
    "location_picker",
    path=str(_LOCATION_PICKER_PATH),
)


def geo_capture(button_label: str, key: str):
    return _geo_capture(buttonLabel=button_label, key=key, default=None)


def location_picker(
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    has_selection: bool,
    key: str,
):
    return _location_picker(
        latitude=latitude,
        longitude=longitude,
        radiusM=radius_m,
        hasSelection=has_selection,
        key=key,
        default=None,
    )


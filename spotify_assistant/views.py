"""Converts Spotify Web API objects into the compact format the panel renders."""
from __future__ import annotations


def pick_image(images: list[dict] | None, min_size: int) -> str | None:
    """Smallest image that is at least min_size px (Spotify lists them from largest to smallest)."""
    if not images:
        return None
    fitting = [image for image in images if (image.get("width") or 0) >= min_size]
    return (fitting[-1] if fitting else images[0])["url"]


def item_row(item: dict, image_size: int = 64) -> dict:
    if item.get("type") == "episode":
        show = item.get("show") or {}
        row = {
            "subtitle": show.get("name", ""),
            "image": pick_image(item.get("images") or show.get("images"), image_size),
            "release_date": item.get("release_date"),
        }
    else:
        row = {
            "subtitle": ", ".join(artist["name"] for artist in item.get("artists", [])),
            "image": pick_image((item.get("album") or {}).get("images"), image_size),
        }
    return {
        "uri": item["uri"],
        "type": item.get("type", "track"),
        "title": item["name"],
        "duration_ms": item.get("duration_ms") or 0,
        **row,
    }

"""Podcast-app subscribe links for the public listening page.

Fill in the IDs once each directory listing goes live; until then the button
still renders (icon + name) but is marked "Soon" and isn't clickable.

- Apple Podcasts ID: the number after ``/id`` in the show's
  ``podcasts.apple.com/.../id1234567890`` URL. Overcast and Pocket Casts index
  Apple's directory, so their links are derived from the same ID.
- Spotify show ID: the part after ``/show/`` in ``open.spotify.com/show/<id>``.
- Amazon Music and iHeart: paste the full show URL (their IDs aren't derivable).

All are read from env vars; CI passes them from GitHub repo variables, so a
listing can go live with ``gh variable set`` and no code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

APPLE_PODCASTS_ID = os.environ.get("KELLBLOG_APPLE_PODCASTS_ID", "").strip()
SPOTIFY_SHOW_ID = os.environ.get("KELLBLOG_SPOTIFY_SHOW_ID", "").strip()
AMAZON_MUSIC_URL = os.environ.get("KELLBLOG_AMAZON_MUSIC_URL", "").strip()
IHEART_URL = os.environ.get("KELLBLOG_IHEART_URL", "").strip()


@dataclass(frozen=True)
class ListenPlatform:
    key: str
    name: str
    url: str  # empty → not live yet
    icon_svg: str  # inner markup of a 24x24 SVG, colours included


# Brand marks from Simple Icons 13.21.0 (https://simpleicons.org, CC0).
_APPLE_ICON = "M5.34 0A5.328 5.328 0 000 5.34v13.32A5.328 5.328 0 005.34 24h13.32A5.328 5.328 0 0024 18.66V5.34A5.328 5.328 0 0018.66 0zm6.525 2.568c2.336 0 4.448.902 6.056 2.587 1.224 1.272 1.912 2.619 2.264 4.392.12.59.12 2.2.007 2.864a8.506 8.506 0 01-3.24 5.296c-.608.46-2.096 1.261-2.336 1.261-.088 0-.096-.091-.056-.46.072-.592.144-.715.48-.856.536-.224 1.448-.874 2.008-1.435a7.644 7.644 0 002.008-3.536c.208-.824.184-2.656-.048-3.504-.728-2.696-2.928-4.792-5.624-5.352-.784-.16-2.208-.16-3 0-2.728.56-4.984 2.760-5.672 5.528-.184.752-.184 2.584 0 3.336.456 1.832 1.640 3.512 3.192 4.512.304.2.672.408.824.472.336.144.408.264.472.856.04.36.03.464-.056.464-.056 0-.464-.176-.896-.384l-.04-.03c-2.472-1.216-4.056-3.274-4.632-6.012-.144-.706-.168-2.392-.03-3.04.36-1.740 1.048-3.1 2.192-4.304 1.648-1.737 3.768-2.656 6.128-2.656zm.134 2.81c.409.004.803.04 1.106.106 2.784.62 4.76 3.408 4.376 6.174-.152 1.114-.536 2.03-1.216 2.88-.336.43-1.152 1.15-1.296 1.15-.023 0-.048-.272-.048-.603v-.605l.416-.496c1.568-1.878 1.456-4.502-.256-6.224-.664-.67-1.432-1.064-2.424-1.246-.64-.118-.776-.118-1.448-.008-1.02.167-1.81.562-2.512 1.256-1.72 1.704-1.832 4.342-.264 6.222l.413.496v.608c0 .336-.027.608-.06.608-.03 0-.264-.16-.512-.36l-.034-.011c-.832-.664-1.568-1.842-1.872-2.997-.184-.698-.184-2.024.008-2.72.504-1.878 1.888-3.335 3.808-4.019.41-.145 1.133-.22 1.814-.211zm-.13 2.99c.31 0 .62.06.844.178.488.253.888.745 1.04 1.259.464 1.578-1.208 2.96-2.72 2.254h-.015c-.712-.331-1.096-.956-1.104-1.77 0-.733.408-1.371 1.112-1.745.224-.117.534-.176.844-.176zm-.011 4.728c.988-.004 1.706.349 1.97.97.198.464.124 1.932-.218 4.302-.232 1.656-.36 2.074-.68 2.356-.44.39-1.064.498-1.656.288h-.003c-.716-.257-.87-.605-1.164-2.644-.341-2.37-.416-3.838-.218-4.302.262-.616.974-.966 1.970-.970z"
_SPOTIFY_ICON = "M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"
_OVERCAST_ICON = "M12 24C5.389 24.018.017 18.671 0 12.061V12C0 5.35 5.351 0 12 0s12 5.35 12 12c0 6.649-5.351 12-12 12zm0-4.751l.9-.899-.9-3.45-.9 3.45.9.899zm-1.15-.05L10.4 20.9l1.05-1.052-.6-.649zm2.3 0l-.6.601 1.05 1.051-.45-1.652zm.85 3.102L12 20.3l-2 2.001c.65.1 1.3.199 2 .199s1.35-.05 2-.199zM12 1.5C6.201 1.5 1.5 6.201 1.5 12c-.008 4.468 2.825 8.446 7.051 9.899l2.25-8.35c-.511-.372-.809-.968-.801-1.6 0-1.101.9-2.001 2-2.001s2 .9 2 2.001c0 .649-.301 1.2-.801 1.6l2.25 8.35c4.227-1.453 7.06-5.432 7.051-9.899 0-5.799-4.701-10.5-10.5-10.5zm6.85 15.7c-.255.319-.714.385-1.049.15-.313-.207-.4-.628-.194-.941.014-.021.028-.04.044-.06 0 0 1.35-1.799 1.35-4.35s-1.35-4.35-1.350-4.35c-.239-.289-.198-.719.091-.957.02-.016.039-.031.06-.044.335-.235.794-.169 1.049.15.1.101 1.65 2.15 1.65 5.2S18.949 17.1 18.85 17.2zm-3.651-1.95c-.3-.3-.249-.85.051-1.15 0 0 .75-.799.75-2.1s-.75-2.051-.75-2.1c-.3-.301-.3-.801-.051-1.15.232-.303.666-.357.969-.125.029.022.056.047.082.074C16.301 8.75 17.5 10 17.5 12s-1.199 3.25-1.25 3.301c-.301.299-.75.25-1.051-.051zm-6.398 0c-.301.301-.75.35-1.051.051C7.699 15.199 6.5 14 6.5 12s1.199-3.199 1.25-3.301c.301-.299.801-.299 1.051.051.3.3.249.85-.051 1.15 0 .049-.75.799-.75 2.1s.75 2.1.75 2.1c.3.3.351.799.051 1.15zm-2.602 2.101c-.335.234-.794.169-1.05-.15C5.051 17.1 3.5 15.05 3.5 12s1.551-5.1 1.649-5.2c.256-.319.715-.386 1.05-.15.313.206.4.628.194.941-.013.02-.028.04-.043.059C6.35 7.65 5 9.449 5 12s1.35 4.35 1.35 4.35c.25.3.15.75-.151 1.001z"
_POCKETCASTS_ICON = "M12,0C5.372,0,0,5.372,0,12c0,6.628,5.372,12,12,12c6.628,0,12-5.372,12-12C24,5.372,18.628,0,12,0z M15.564,12c0-1.968-1.596-3.564-3.564-3.564c-1.968,0-3.564,1.595-3.564,3.564c0,1.968,1.595,3.564,3.564,3.564V17.6c-3.093,0-5.6-2.507-5.6-5.6c0-3.093,2.507-5.6,5.6-5.6c3.093,0,5.6,2.507,5.6,5.6H15.564z M19,12c0-3.866-3.134-7-7-7c-3.866,0-7,3.134-7,7c0,3.866,3.134,7,7,7v2.333c-5.155,0-9.333-4.179-9.333-9.333c0-5.155,4.179-9.333,9.333-9.333c5.155,0,9.333,4.179,9.333,9.333H19z"
# Simple Icons only ships wordmarks for these two, unreadable at button size,
# so use simple brand-coloured marks; the button label carries the name.
_AMAZON_MUSIC_SVG = (
    '<rect width="24" height="24" rx="5.5" fill="#25D1DA"/>'
    '<path fill="#fff" d="M15.5 4.5v8.9a2.6 2.6 0 1 1-1.6-2.4V7.6h-3.6v7.8a2.6 2.6 0 1 1-1.6-2.4V4.5z"/>'
    '<path fill="none" stroke="#fff" stroke-width="1.4" stroke-linecap="round" d="M5.5 19.2c3.9 1.9 9.1 1.9 13 0"/>'
)
_IHEART_SVG = (
    '<path fill="#C6002B" d="M12 21.3S3.6 16.2 1.7 11.1C.3 7.4 2.6 3.2 6.6 3.2c2.3 0 3.9 1.3 5.4 3.2 1.5-1.9 3.1-3.2 5.4-3.2 4 0 6.3 4.2 4.9 7.9-1.9 5.1-10.3 10.2-10.3 10.2z"/>'
    '<circle cx="12" cy="9.6" r="1.6" fill="#fff"/>'
    '<path fill="#fff" d="M11 12.4h2v4.4h-2z"/>'
)


def _brand(color: str, path: str) -> str:
    return f'<path fill="{color}" d="{path}"/>'


RSS_ICON = "M19.199 24C19.199 13.467 10.533 4.8 0 4.8V0c13.165 0 24 10.835 24 24h-4.801zM3.291 17.415c1.814 0 3.293 1.479 3.293 3.295 0 1.813-1.485 3.29-3.301 3.29C1.47 24 0 22.526 0 20.71s1.475-3.294 3.291-3.295zM15.909 24h-4.665c0-6.169-5.075-11.245-11.244-11.245V8.09c8.727 0 15.909 7.184 15.909 15.91z"


def listen_platforms(
    apple_id: str = APPLE_PODCASTS_ID,
    spotify_id: str = SPOTIFY_SHOW_ID,
    amazon_url: str = AMAZON_MUSIC_URL,
    iheart_url: str = IHEART_URL,
) -> list[ListenPlatform]:
    apple = f"https://podcasts.apple.com/podcast/id{apple_id}" if apple_id else ""
    spotify = f"https://open.spotify.com/show/{spotify_id}" if spotify_id else ""
    overcast = f"https://overcast.fm/itunes{apple_id}" if apple_id else ""
    pocketcasts = f"https://pca.st/itunes/{apple_id}" if apple_id else ""
    return [
        ListenPlatform("apple", "Apple Podcasts", apple, _brand("#9933CC", _APPLE_ICON)),
        ListenPlatform("spotify", "Spotify", spotify, _brand("#1DB954", _SPOTIFY_ICON)),
        ListenPlatform("amazon", "Amazon Music", amazon_url, _AMAZON_MUSIC_SVG),
        ListenPlatform("iheart", "iHeart", iheart_url, _IHEART_SVG),
        ListenPlatform("overcast", "Overcast", overcast, _brand("#FC7E0F", _OVERCAST_ICON)),
        ListenPlatform("pocketcasts", "Pocket Casts", pocketcasts, _brand("#F43E37", _POCKETCASTS_ICON)),
    ]

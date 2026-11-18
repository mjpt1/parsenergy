"""Map tiles, served from our own server.

Three public tile services have now refused this site in turn: OpenStreetMap
blocked the traffic, map.ir answers with an "unauthorized" watermark because
this account's key lacks the tile scope, and Esri returns 403 to Iranian
addresses. Each failure looked different in the browser and identical in the
status code — a 200 carrying a picture that says "no".

So the browser stops talking to any of them. It asks *this* server for a tile,
and the server fetches it. That changes the problem from "which service will
Iranian consumer ISPs allow today" to "which service can this one machine
reach", which is a question we can answer once, cache, and re-answer
automatically if it ever changes.

Tiles are immutable, so a fetched tile is cached on disk and served from there
afterwards; a working upstream is remembered so we do not re-probe per tile.

SystemParameter keys:
    map_tile_upstream   pin one upstream by name, skipping the probe
    map_api_key         map.ir key, used if the map.ir upstream is reachable
    map_carto_key       Carto key; without it the styled basemaps are skipped
"""
from __future__ import annotations

import hashlib
import logging
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from apps.core.models import SystemParameter

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 12
CACHE_DIR = Path(settings.MEDIA_ROOT) / 'tilecache'
UPSTREAM_CACHE_KEY = 'map:tile_upstream'
UPSTREAM_CACHE_SECONDS = 3600

#: Below this, nothing can be a street map — a blank, or an error glyph.
MIN_REAL_TILE_BYTES = 800

#: Two tiles far enough apart that no genuine map renders them identically.
PROBE_A = (12, 2632, 1612)   # Tehran
PROBE_B = (12, 1205, 1539)   # open Atlantic, west of Europe


def _mapir_url(z, x, y):
    # map.ir has no "city" layer (GWC 400 "Unknown layer city"); its raster
    # XYZ layer is Shiveh:Shiveh in Web Mercator.
    return f'https://map.ir/shiveh/xyz/1.0.0/Shiveh:Shiveh@EPSG:3857@png/{z}/{x}/{y}.png'


def _osm_url(z, x, y):
    return f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'


def _esri_url(z, x, y):
    return ('https://server.arcgisonline.com/ArcGIS/rest/services/'
            f'World_Street_Map/MapServer/tile/{z}/{y}/{x}')


def _wikimedia_url(z, x, y):
    return f'https://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png'


def _carto_dark_url(z, x, y):
    return f'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png{_carto_key()}'


def _carto_light_url(z, x, y):
    return f'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png{_carto_key()}'


def _carto_key() -> str:
    """Carto's basemaps stopped being open: without a key they answer 200 with
    a tile that reads "API KEY REQUIRED" across it. The probe below catches
    that, so the styled map simply does not engage until a key is configured
    under the `map_carto_key` parameter.
    """
    key = _param('map_carto_key').strip()
    return f'?api_key={key}' if key else ''


#: Tried in order. The first that returns a real image wins and is remembered.
UPSTREAMS = (
    ('mapir', _mapir_url),
    ('wikimedia', _wikimedia_url),
    ('osm', _osm_url),
    ('esri', _esri_url),
)

#: Styled basemaps, keyed by the UI theme. These are asked for explicitly by
#: `?theme=`; they are not part of the automatic probe order, because a tile
#: that fits the dark UI is a preference, not a fallback — if Carto is
#: unreachable the plain upstreams above still have to produce a map.
def _tomtom_satellite_url(z, x, y):
    # Official, licensed imagery; needs `map_tomtom_key`. Without a key the
    # probe gets no image and the next satellite source is used.
    key = _param('map_tomtom_key').strip()
    return f'https://api.tomtom.com/map/1/tile/sat/main/{z}/{x}/{y}.jpg?key={key}'


def _google_satellite_url(z, x, y):
    # Esri's World_Imagery returns 403 to Iranian addresses; Google reaches us.
    return f'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}'


def _bing_satellite_url(z, x, y):
    quadkey = ''.join(
        str((1 if x >> (i - 1) & 1 else 0) + (2 if y >> (i - 1) & 1 else 0))
        for i in range(z, 0, -1))
    return f'https://ecn.t0.tiles.virtualearth.net/tiles/a{quadkey}.jpeg?g=1'


#: Each theme is a list of sources tried in order. If every one fails, the
#: plain upstreams (map.ir first) still produce a map, so a map always shows.
STYLED = {
    'dark': (('carto-dark', _carto_dark_url),),
    'light': (('carto-light', _carto_light_url),),
    'satellite': (
        ('tomtom-satellite', _tomtom_satellite_url),
        ('google-satellite', _google_satellite_url),
        ('bing-satellite', _bing_satellite_url),
    ),
}


def _param(key: str, default: str = '') -> str:
    param = SystemParameter.objects.filter(key=key).first()
    return param.value if param else default


def _headers(name: str) -> dict:
    headers = {
        'User-Agent': 'ParsEnergy/1.0 (+https://pars-tida.ir)',
        'Accept': 'image/png,image/jpeg,*/*',
    }
    if name == 'mapir':
        key = _param('map_api_key').strip()
        if key:
            headers['x-api-key'] = key
    return headers


def _looks_like_an_image(body: bytes, content_type: str) -> bool:
    if len(body) < MIN_REAL_TILE_BYTES:
        return False
    if body[:4] == b'\x89PNG' or body[:2] == b'\xff\xd8':
        return True
    return content_type.startswith('image/')


def _serves_real_maps(name: str, build_url) -> bool:
    """Tell a working upstream from one that politely refuses in PNG.

    Size is no help: map.ir's "unauthorized" notice is a 36 KB image, larger
    than plenty of genuine tiles, and OpenStreetMap's block notice is a valid
    PNG too. What gives every refusal away is that it is the *same* picture
    whatever tile you ask for — so ask for two on opposite sides of the world.
    Any real map draws those differently.
    """
    first, _ = _fetch_raw(name, build_url, *PROBE_A)
    if first is None:
        return False
    second, _ = _fetch_raw(name, build_url, *PROBE_B)
    if second is None:
        return False
    if first == second:
        logger.info('Tile upstream %s returns one fixed image — refusing it', name)
        return False
    return True


def _fetch_raw(name: str, build_url, z: int, x: int, y: int):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(build_url(z, x, y), headers=_headers(name))
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
            content_type = response.headers.get('Content-Type', '')
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info('Tile upstream %s unreachable: %s', name, exc)
        return None, ''
    if not _looks_like_an_image(body, content_type):
        logger.info('Tile upstream %s returned no image (%s bytes, %s)',
                    name, len(body), content_type)
        return None, ''
    return body, content_type or 'image/png'


def fetch_tile(z: int, x: int, y: int, theme: str = ''):
    """Return ``(bytes, content_type)`` for one tile, or ``(None, '')``.

    Prefers the upstream that worked last time; falls back to probing the rest
    so a service going dark fixes itself without a deploy.

    ``theme`` asks for a styled basemap matching the UI. It is tried first and
    then forgotten about: if it is unreachable we fall straight through to the
    ordinary upstreams, because a plain map is better than no map.
    """
    for name, build_url in STYLED.get(theme, ()):
        if name == 'tomtom-satellite' and not _param('map_tomtom_key').strip():
            continue
        key = f'{UPSTREAM_CACHE_KEY}:{name}'
        reachable = cache.get(key)
        if reachable is None:
            reachable = _serves_real_maps(name, build_url)
            cache.set(key, reachable, UPSTREAM_CACHE_SECONDS)
        if reachable:
            body, content_type = _fetch_raw(name, build_url, z, x, y)
            if body is not None:
                return body, content_type
            cache.delete(key)

    pinned = _param('map_tile_upstream').strip()
    order = list(UPSTREAMS)
    preferred = pinned or cache.get(UPSTREAM_CACHE_KEY)
    if preferred:
        order.sort(key=lambda item: item[0] != preferred)

    for name, build_url in order:
        # A remembered upstream is trusted; a new one must prove it serves
        # real maps before we start handing its pictures to customers.
        if name != preferred and not _serves_real_maps(name, build_url):
            if pinned:
                break
            continue
        body, content_type = _fetch_raw(name, build_url, z, x, y)
        if body is not None:
            if name != preferred:
                logger.info('Tile upstream now: %s', name)
            cache.set(UPSTREAM_CACHE_KEY, name, UPSTREAM_CACHE_SECONDS)
            return body, content_type
        if pinned:
            break  # an explicit choice is not silently overridden
        cache.delete(UPSTREAM_CACHE_KEY)
    return None, ''


def cached_tile_path(z: int, x: int, y: int, theme: str = '') -> Path:
    """Shard by a hash so no directory collects millions of entries.

    The theme is part of the key: a dark tile and a light tile of the same
    square are different pictures and must not overwrite each other.
    """
    key = f'{theme}/{z}/{x}/{y}' if theme else f'{z}/{x}/{y}'
    digest = hashlib.sha1(key.encode()).hexdigest()
    name = f'{theme}_{z}_{x}_{y}.img' if theme else f'{z}_{x}_{y}.img'
    return CACHE_DIR / digest[:2] / digest[2:4] / name

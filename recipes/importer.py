"""Read a recipe from a web page that a person pastes.

The server fetches the page, so the address is checked first: http(s) on the standard ports only,
and public internet addresses only, never the server's own network. The connection goes to the
address that was checked, so the name cannot point somewhere else in between, and every redirect
is checked again.

Pages that mark their recipe up with schema.org data give its parts directly; otherwise the
visible text is kept for the assistant to read.
"""

import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 10  # per network operation
DEADLINE_SECONDS = 25  # for the whole page, redirects included: a page that trickles in is given up
MAX_REDIRECTS = 3
MAX_TEXT = 12_000
MAX_INGREDIENTS = 60
MAX_STEPS = 40
USER_AGENT = "menuamano/1.0 (importador de recetas; +https://www.menuamano.com)"
REDIRECTS = {301, 302, 303, 307, 308}
# IPv6 ranges that carry an IPv4 address inside (IPv4-compatible and mapped, NAT64, 6to4, Teredo):
# the address inside could be a private one, so they are refused.
EMBEDDED_IPV4_NETWORKS = [
    ipaddress.ip_network(network)
    for network in ("::/96", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
]


class RecipeImportError(Exception):
    """`message` is shown to the person (Spanish)."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


# --- Fetching ------------------------------------------------------------------------------------


def check_url(url):
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise RecipeImportError("Pega el enlace completo de la receta, empezando por https://")
    if parts.username or parts.password:
        raise RecipeImportError("El enlace no puede llevar usuario ni contraseña.")
    try:
        port = parts.port
    except ValueError:
        raise RecipeImportError("El enlace no es válido.") from None
    if port not in (None, 80, 443):
        raise RecipeImportError("Ese enlace usa un puerto no permitido.")
    return parts


def _is_public(address):
    if not address.is_global:
        return False
    return address.version == 4 or not any(address in network for network in EMBEDDED_IPV4_NETWORKS)


def public_address(host, port):
    """The address to connect to, only if every address of the name is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise RecipeImportError("No se encuentra esa página. Revisa el enlace.") from None
    addresses = [ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos]
    if not addresses or not all(_is_public(address) for address in addresses):
        raise RecipeImportError("Ese enlace no lleva a una página pública de internet.")
    return str(addresses[0])


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, address, **kwargs):
        super().__init__(host, **kwargs)
        self._address = address

    def connect(self):
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, **kwargs):
        self._tls = ssl.create_default_context()
        super().__init__(host, context=self._tls, **kwargs)
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)  # the certificate is still checked


def _read(response, deadline):
    """The body, within MAX_BYTES and before `deadline`."""
    chunks, size = [], 0
    while True:
        if time.monotonic() > deadline:
            raise RecipeImportError("La página tarda demasiado en responder. Prueba más tarde.")
        chunk = response.read1(64 * 1024)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > MAX_BYTES:
            raise RecipeImportError("La página es demasiado grande para leerla.")
        chunks.append(chunk)


def _decode(body, charset):
    """The page's text in its declared charset, or UTF-8 when that is unknown or not a text one."""
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch_html(url):
    deadline = time.monotonic() + DEADLINE_SECONDS
    for _ in range(MAX_REDIRECTS + 1):
        if time.monotonic() > deadline:
            raise RecipeImportError("La página tarda demasiado en responder. Prueba más tarde.")
        parts = check_url(url)
        secure = parts.scheme == "https"
        port = parts.port or (443 if secure else 80)
        address = public_address(parts.hostname, port)
        connection_class = _PinnedHTTPSConnection if secure else _PinnedHTTPConnection
        connection = connection_class(parts.hostname, address, port=port, timeout=TIMEOUT_SECONDS)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        try:
            connection.request("GET", path, headers={
                "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "es,en;q=0.5",
            })
            response = connection.getresponse()
            if response.status in REDIRECTS:
                location = response.getheader("Location")
                if not location:
                    raise RecipeImportError("La página no se ha podido abrir.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise RecipeImportError(f"La página no se ha podido abrir (error {response.status}).")
            if "html" not in (response.getheader("Content-Type") or "").lower():
                raise RecipeImportError("Ese enlace no es una página web con una receta.")
            return _decode(_read(response, deadline), response.headers.get_content_charset())
        except (OSError, http.client.HTTPException) as exc:  # includes timeouts and TLS errors
            raise RecipeImportError("No se ha podido abrir la página. Revisa el enlace o prueba más tarde.") from exc
        finally:
            connection.close()
    raise RecipeImportError("La página redirige demasiadas veces.")


# --- Reading -------------------------------------------------------------------------------------


class _PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.json_blocks, self.text, self.title = [], [], ""
        self._skip = 0
        self._json = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and (dict(attrs).get("type") or "").lower() == "application/ld+json":
            self._json = []
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "script" and self._json is not None:
            self.json_blocks.append("".join(self._json))
            self._json = None
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._json is not None:
            self._json.append(data)
        elif self._in_title:
            self.title += data
        elif not self._skip:
            self.text.append(data)


def _clean(value, limit=1000):
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _is_recipe(node):
    kind = node.get("@type")
    return "Recipe" in (kind if isinstance(kind, list) else [kind])


def _find_recipe(node):
    if isinstance(node, list):
        for child in node:
            found = _find_recipe(child)
            if found:
                return found
    elif isinstance(node, dict):
        if _is_recipe(node):
            return node
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            found = _find_recipe(node.get(key))
            if found:
                return found
    return None


def _steps(value):
    if isinstance(value, str):
        return [s for s in (_clean(p) for p in re.split(r"\n+|(?<=\.)\s+(?=\d+\.\s)", value)) if s]
    if isinstance(value, list):
        return [step for item in value for step in _steps(item)]
    if isinstance(value, dict):
        if value.get("itemListElement"):
            return _steps(value["itemListElement"])
        text = _clean(value.get("text") or value.get("name"))
        return [text] if text else []
    return []


def _minutes(value):
    match = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", str(value or "").strip())
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0) if match else 0


def _servings(value):
    for item in value if isinstance(value, list) else [value]:
        match = re.search(r"\d+", str(item or ""))
        if match and 1 <= int(match.group()) <= 50:
            return int(match.group())
    return None


def _schema_recipe(recipe):
    ingredients = recipe["recipeIngredient"]
    return {
        "format": "schema.org",
        "name": _clean(recipe.get("name"), 120),
        "description": _clean(recipe.get("description"), 500),
        "servings": _servings(recipe.get("recipeYield")),
        "prep_minutes": _minutes(recipe.get("prepTime")),
        "cook_minutes": _minutes(recipe.get("cookTime")),
        "ingredients": [_clean(i, 200) for i in (ingredients if isinstance(ingredients, list) else [ingredients])][:MAX_INGREDIENTS],
        "instructions": _steps(recipe.get("recipeInstructions"))[:MAX_STEPS],
    }


def extract(page):
    parser = _PageParser()
    parser.feed(page)
    for block in parser.json_blocks:
        try:
            recipe = _find_recipe(json.loads(block))
            if recipe and recipe.get("recipeIngredient"):
                return _schema_recipe(recipe)
        except (ValueError, RecursionError):  # malformed or absurdly nested data: try the next block
            continue
    text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
    if len(text) < 200:
        raise RecipeImportError("No se ha encontrado ninguna receta en esa página.")
    return {"format": "text", "title": _clean(parser.title, 200), "text": text[:MAX_TEXT]}


def read_recipe(url):
    """The recipe found at `url`, as plain data for the assistant. Network calls happen here."""
    source = extract(fetch_html(url))
    source["url"] = url.strip()
    return source

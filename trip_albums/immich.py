"""Thin Immich HTTP client. The only module that talks to the Immich API."""


class ImmichError(Exception):
    """Raised on a non-2xx response or an unexpected response shape."""


class ImmichClient:
    def __init__(self, base_url, api_key, session=None, page_size=1000, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.page_size = page_size
        self.timeout = timeout
        if session is None:
            import requests  # imported lazily so pure tests need no network stack
            session = requests.Session()
        self.session = session

    # -- low-level ----------------------------------------------------------

    def _request(self, method, path, json=None):
        url = f"{self.base_url}{path}"
        headers = {"x-api-key": self.api_key, "Accept": "application/json"}
        resp = self.session.request(method, url, headers=headers, json=json, timeout=self.timeout)
        if not (200 <= resp.status_code < 300):
            body = getattr(resp, "text", "")
            raise ImmichError(f"{method} {path} failed: HTTP {resp.status_code} {body}")
        return resp

    # -- assets -------------------------------------------------------------

    def search_all_assets(self, taken_after=None, taken_before=None):
        """Return all visible IMAGE/VIDEO-eligible assets with exif, across pages.

        Omits `type` (single-valued in the API) and filters client-side later;
        excludes deleted assets and restricts to the normal timeline. Optional
        `taken_after`/`taken_before` (ISO-8601 strings) push date filtering
        server-side via the API's `takenAfter`/`takenBefore`.
        """
        items = []
        page = 1
        while True:
            body = {
                "withExif": True,
                "withDeleted": False,
                "visibility": "timeline",
                "page": page,
                "size": self.page_size,
            }
            if taken_after is not None:
                body["takenAfter"] = taken_after
            if taken_before is not None:
                body["takenBefore"] = taken_before
            resp = self._request("POST", "/api/search/metadata", json=body)
            data = resp.json()
            assets = data.get("assets")
            if assets is None or "items" not in assets:
                raise ImmichError("/api/search/metadata: unexpected response shape (no assets.items)")
            items.extend(assets["items"])
            next_page = assets.get("nextPage")
            if not next_page:
                break
            page = int(next_page)
        return items

    # -- albums -------------------------------------------------------------

    def list_albums(self):
        return self._request("GET", "/api/albums").json()

    def create_album(self, name, description, asset_ids):
        body = {"albumName": name, "description": description, "assetIds": asset_ids}
        return self._request("POST", "/api/albums", json=body).json()

    def rename_album(self, album_id, name):
        return self._request("PATCH", f"/api/albums/{album_id}", json={"albumName": name}).json()

    def add_assets(self, album_id, asset_ids):
        return self._request("PUT", f"/api/albums/{album_id}/assets", json={"ids": asset_ids}).json()

    def get_album(self, album_id):
        return self._request("GET", f"/api/albums/{album_id}").json()

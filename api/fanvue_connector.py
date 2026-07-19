import math
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config import config
from api.fanvue_oauth import get_valid_access_token, refresh_if_expired_or_forced

_retry_policy = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException),
)


class FanvueConnector:
    """Real Fanvue REST API client (OAuth 2.0 + version header)."""

    def __init__(self):
        self.base_url = config.FANVUE_BASE_URL.rstrip("/")
        self.timeout = 20
        self.upload_timeout = 120

    def _headers(self, *, json_body: bool = True) -> dict:
        headers = {
            "Authorization": f"Bearer {get_valid_access_token()}",
            "X-Fanvue-API-Version": config.FANVUE_API_VERSION,
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    @_retry_policy
    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", self.timeout)
        response = requests.request(
            method, url, headers=self._headers(), timeout=timeout, **kwargs
        )
        if response.status_code == 401:
            # Single-flight refresh (Fanvue refresh tokens are single-use).
            # Do NOT nest force-refresh inside tenacity storms — one retry only.
            try:
                refresh_if_expired_or_forced(force=True)
            except Exception as e:
                raise requests.HTTPError(
                    f"401 {method} {path}: auth refresh failed: {e}",
                    response=response,
                ) from e
            response = requests.request(
                method, url, headers=self._headers(), timeout=timeout, **kwargs
            )
        if not response.ok:
            detail = response.text[:500]
            raise requests.HTTPError(
                f"{response.status_code} {method} {path}: {detail}",
                response=response,
            )
        if not response.content:
            return {}
        ctype = response.headers.get("Content-Type", "")
        if "application/json" in ctype:
            return response.json()
        return {"_raw": response.text}

    def get_current_user(self) -> dict:
        return self._request("GET", "/users/me")

    def get_creator_uuid(self) -> str:
        return self.get_current_user()["uuid"]

    @_retry_policy
    def send_message(self, fan_uuid: str, text: str) -> dict:
        """Send a plain text message to a fan (chat must already exist)."""
        return self._request(
            "POST",
            f"/chats/{fan_uuid}/message",
            json={"text": text},
        )

    @_retry_policy
    def send_media_message(
        self,
        fan_uuid: str,
        media_uuids: list,
        text: str = None,
        *,
        fallback_uuids: list = None,
    ) -> dict:
        """
        Send unlocked (free) vault media — omit price so Fanvue does not lock it.
        Always include a tiny text so Fanvue renders a real media bubble (media-only
        payloads have shown up as empty "[sent a free photo]" placeholders).
        """
        uuids = [u for u in (media_uuids or []) if u]
        if not uuids:
            raise ValueError("send_media_message requires at least one media_uuid")
        try:
            chosen = self._preflight_vault_uuid(uuids, fallback_uuids=fallback_uuids)
        except ValueError as e:
            raise ValueError(f"free media preflight failed: {e}") from e

        payload: dict = {
            "mediaUuids": [chosen],
            "text": ((text or "").strip() or "😏")[:500],
        }
        return self._request(
            "POST",
            f"/chats/{fan_uuid}/message",
            json=payload,
        )

    def creator_media_in_chat(
        self,
        fan_uuid: str,
        creator_uuid: str,
        media_uuid: str,
        *,
        lookback: int = 40,
        aliases: Optional[List[str]] = None,
    ) -> bool:
        """
        True if Fanvue chat history shows the creator already sent this media_uuid
        (or an alias / previous uuid). Used to verify free/PPV delivery.
        """
        want = {u for u in ([media_uuid] + list(aliases or [])) if u}
        if not want:
            return False
        try:
            msgs = self.get_messages(fan_uuid, size=lookback)
        except Exception:
            return False
        for msg in msgs:
            sender = msg.get("sender")
            sid = sender.get("uuid") if isinstance(sender, dict) else sender
            if sid != creator_uuid:
                continue
            for uid in msg.get("mediaUuids") or []:
                if uid in want:
                    return True
            # Some payloads nest media
            for m in msg.get("media") or []:
                if isinstance(m, dict) and m.get("uuid") in want:
                    return True
        return False

    def _preflight_vault_uuid(
        self,
        media_uuids: list,
        *,
        fallback_uuids: list = None,
    ) -> str:
        """Pick first vault UUID that resolves via GET /media — avoid empty bubbles."""
        candidates: List[str] = []
        for u in list(media_uuids or []) + list(fallback_uuids or []):
            if u and u not in candidates:
                candidates.append(u)
        if not candidates:
            raise ValueError("media preflight requires at least one media_uuid")
        last_err: Optional[Exception] = None
        for uid in candidates:
            try:
                meta = self.get_media(uid, variants="thumbnail")
                if meta:
                    return uid
                last_err = ValueError(f"media {uid[:8]}… not found in vault")
            except Exception as e:
                last_err = e
                continue
        raise ValueError(
            f"media preflight failed for {candidates[0][:8]}…: {last_err}"
        ) from last_err

    @_retry_policy
    def send_ppv_message(
        self,
        fan_uuid: str,
        media_uuids: list,
        price_dollars: float,
        text: str = None,
        media_preview_uuid: str = None,
        *,
        fallback_uuids: list = None,
    ) -> dict:
        """
        Send pay-to-view content in chat.

        `price` is sent in USD cents (minimum 300 = $3.00).
        Media must already exist in the creator vault (`media_uuids`).
        Always include a tiny text — media-only payloads have rendered empty.
        """
        chosen = self._preflight_vault_uuid(
            media_uuids, fallback_uuids=fallback_uuids
        )
        price_cents = max(300, int(round(float(price_dollars) * 100)))
        payload = {
            "mediaUuids": [chosen],
            "price": price_cents,
            "text": ((text or "").strip() or "🔒")[:500],
        }
        if media_preview_uuid:
            payload["mediaPreviewUuid"] = media_preview_uuid
        return self._request(
            "POST",
            f"/chats/{fan_uuid}/message",
            json=payload,
        )

    @_retry_policy
    def delete_message(self, fan_uuid: str, message_uuid: str) -> None:
        """
        Unsend a chat message. Purchased PPV cannot be deleted (API returns 400).
        """
        if not fan_uuid or not message_uuid:
            raise ValueError("delete_message requires fan_uuid and message_uuid")
        url = f"{self.base_url}/chats/{fan_uuid}/messages/{message_uuid}"
        timeout = self.timeout
        response = requests.request(
            "DELETE", url, headers=self._headers(), timeout=timeout
        )
        if response.status_code == 401:
            refresh_if_expired_or_forced(force=True)
            response = requests.request(
                "DELETE", url, headers=self._headers(), timeout=timeout
            )
        if response.status_code == 204:
            return
        if not response.ok:
            detail = (response.text or "")[:500]
            raise requests.HTTPError(
                f"{response.status_code} DELETE /chats/.../messages/...: {detail}",
                response=response,
            )

    def find_message_uuid_for_media(
        self,
        fan_uuid: str,
        media_uuid: str,
        *,
        creator_uuid: str,
        lookback: int = 30,
        aliases: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Newest creator message that carries this media uuid (or alias)."""
        want = {u for u in ([media_uuid] + list(aliases or [])) if u}
        if not want:
            return None
        try:
            msgs = self.get_messages(fan_uuid, size=lookback)
        except Exception:
            return None
        for msg in msgs:
            sender = msg.get("sender")
            sid = sender.get("uuid") if isinstance(sender, dict) else sender
            if sid != creator_uuid:
                continue
            muids = set(msg.get("mediaUuids") or [])
            for m in msg.get("media") or []:
                if isinstance(m, dict) and m.get("uuid"):
                    muids.add(m["uuid"])
            if muids & want:
                return msg.get("uuid")
        return None

    # Backwards-compatible alias used by tasks.py
    def send_locked_content(
        self,
        fan_uuid: str,
        file_url: str = None,
        price: float = 0,
        description: str = None,
        content_type: str = "video",
        media_uuid: str = None,
    ) -> dict:
        if not media_uuid:
            raise ValueError(
                "PPV requires a Fanvue vault media_uuid. "
                "Upload content to the vault first and store fanvue_media_uuid in the catalog."
            )
        return self.send_ppv_message(
            fan_uuid,
            media_uuids=[media_uuid],
            price_dollars=price,
            text=description,
        )

    def get_messages(
        self, fan_uuid: str, size: int = 5, *, max_pages: Optional[int] = None
    ) -> list:
        """
        Fetch messages (newest first). Paginates when size > page cap.
        For deep PPV purge, pass size=500+ (up to ~40 pages / ~2000 msgs).
        """
        want = max(1, int(size))
        page_size = min(50, want)  # Fanvue page size is typically capped
        if max_pages is None:
            # Enough pages to satisfy `want`, hard-capped for API safety
            max_pages = min(40, max(4, (want + page_size - 1) // page_size))
        out: list = []
        page = 1
        while len(out) < want and page <= max_pages:
            data = self._request(
                "GET",
                f"/chats/{fan_uuid}/messages",
                params={"size": page_size, "page": page},
            )
            chunk = data.get("data", data if isinstance(data, list) else [])
            if not chunk:
                break
            out.extend(chunk)
            if len(chunk) < page_size:
                break
            page += 1
        return out[:want]

    def get_message_media(
        self,
        fan_uuid: str,
        message_uuid: str,
        media_uuids: List[str],
        *,
        variants: str = "main,thumbnail",
    ) -> dict:
        """
        Resolve signed URLs for media attached to a chat message.

        Fanvue does NOT return URLs on GET /messages — only mediaUuids.
        Use: GET /chats/{fan}/messages/{msg}/media?mediaUuids=...&variants=main
        """
        if not media_uuids:
            return {"results": {}, "errors": []}
        return self._request(
            "GET",
            f"/chats/{fan_uuid}/messages/{message_uuid}/media",
            params={
                "mediaUuids": ",".join(media_uuids[:20]),
                "variants": variants,
            },
        )

    def download_message_image(
        self,
        fan_uuid: str,
        message_uuid: str,
        media_uuid: str,
        *,
        prefer: str = "main",
    ) -> Optional[bytes]:
        """Download image bytes for a fan/creator chat attachment."""
        data = self.get_message_media(
            fan_uuid, message_uuid, [media_uuid], variants=f"{prefer},thumbnail"
        )
        results = data.get("results") or {}
        item = results.get(media_uuid) or {}
        variants = item.get("variants") or []
        url = None
        for v in variants:
            if v.get("variantType") == prefer and v.get("url"):
                url = v["url"]
                break
        if not url:
            for v in variants:
                if v.get("url"):
                    url = v["url"]
                    break
        if not url:
            return None
        resp = requests.get(url, timeout=self.upload_timeout)
        resp.raise_for_status()
        return resp.content

    def list_chats(self, filter_name: str = None, size: int = 20) -> list:
        params = {"size": size, "page": 1}
        if filter_name:
            params["filter"] = filter_name
        data = self._request("GET", "/chats", params=params)
        return data.get("data", [])

    def list_unread_chats(self, size: int = 20) -> list:
        return self.list_chats(filter_name="unread", size=size)

    def fetch_message_text(self, fan_uuid: str, message_uuid: str) -> str:
        """
        Webhook events are metadata-only; fetch the actual message text from the API.
        """
        messages = self.get_messages(fan_uuid, size=20)
        for msg in messages:
            if msg.get("uuid") == message_uuid:
                return msg.get("text") or ""
        # Fallback: newest fan message
        for msg in messages:
            if msg.get("sender") == "fan" and msg.get("text"):
                return msg["text"]
        return ""

    def get_fan_insights(self, fan_uuid: str) -> dict:
        return self._request("GET", f"/insights/fans/{fan_uuid}")

    def get_fan_insights_bulk(self, fan_uuids: List[str]) -> dict:
        """Up to 20 fan UUIDs per request."""
        uuids = [u for u in fan_uuids if u][:20]
        if not uuids:
            return {"results": {}, "errors": []}
        return self._request(
            "GET",
            "/insights/fans",
            params={"fanUuids": ",".join(uuids)},
        )

    def send_typing_indicator(self, fan_uuid: str, is_typing: bool = True) -> None:
        self._request(
            "POST",
            f"/chats/{fan_uuid}/typing",
            json={"isTyping": is_typing},
        )

    # ── Vault / media upload (write:media) ─────────────────────────────

    def list_vault_folders(self, page: int = 1, size: int = 50) -> list:
        data = self._request(
            "GET", "/vault/folders", params={"page": page, "size": size}
        )
        return data.get("data", data if isinstance(data, list) else [])

    def create_vault_folder(self, name: str) -> dict:
        """Create folder; if it already exists (409), return {name, existed: True}."""
        url = f"{self.base_url}/vault/folders"
        response = requests.post(
            url,
            headers=self._headers(),
            json={"name": name},
            timeout=self.timeout,
        )
        if response.status_code == 401:
            refresh_if_expired_or_forced(force=True)
            response = requests.post(
                url,
                headers=self._headers(),
                json={"name": name},
                timeout=self.timeout,
            )
        if response.status_code == 409:
            return {"name": name, "existed": True}
        if not response.ok:
            raise requests.HTTPError(
                f"{response.status_code} POST /vault/folders: {response.text[:500]}",
                response=response,
            )
        data = response.json() if response.content else {"name": name}
        data["existed"] = False
        return data

    def ensure_vault_folder(self, name: str) -> str:
        self.create_vault_folder(name)
        return name

    def attach_media_to_folder(self, folder_name: str, media_uuids: List[str]) -> dict:
        encoded = quote(folder_name, safe="")
        return self._request(
            "POST",
            f"/vault/folders/{encoded}/media",
            json={"mediaUuids": media_uuids},
        )

    def update_media_metadata(
        self,
        media_uuid: str,
        *,
        name: Optional[str] = None,
        caption: Optional[str] = None,
        recommended_price_cents: Optional[int] = None,
    ) -> dict:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name[:255]
        if caption is not None:
            payload["caption"] = caption[:5000]
        if recommended_price_cents is not None:
            payload["recommendedPrice"] = max(
                0, min(50000, int(recommended_price_cents))
            )
        if not payload:
            return {}
        return self._request("PATCH", f"/media/{media_uuid}", json=payload)

    def get_media(self, media_uuid: str, variants: str = "thumbnail") -> dict:
        return self._request(
            "GET",
            f"/media/{media_uuid}",
            params={"variants": variants},
        )

    def check_media_purchased(self, media_uuid: str, fan_uuid: str) -> Optional[bool]:
        """
        True/False if the fan has purchased this media; None if unknown.
        Uses GET /media/{uuid}?purchasedBy=... → `purchasedByFan`.
        """
        data = self._request(
            "GET",
            f"/media/{media_uuid}",
            params={"purchasedBy": fan_uuid},
        )
        val = data.get("purchasedByFan")
        if isinstance(val, bool):
            return val
        return None

    def create_upload_session(
        self,
        *,
        name: str,
        filename: str,
        media_type: str,
        size_bytes: int,
    ) -> dict:
        return self._request(
            "POST",
            "/media/uploads",
            json={
                "name": name[:255],
                "filename": filename[:255],
                "mediaType": media_type,
                "sizeBytes": int(size_bytes),
            },
        )

    def get_upload_part_url(self, upload_id: str, part_number: int) -> str:
        encoded = quote(str(upload_id), safe="")
        data = self._request(
            "GET",
            f"/media/uploads/{encoded}/parts/{part_number}/url",
            timeout=self.upload_timeout,
        )
        if isinstance(data, dict) and data.get("_raw"):
            return data["_raw"].strip()
        if isinstance(data, str):
            return data.strip()
        # Some gateways wrap plain text
        if isinstance(data, dict) and "url" in data:
            return str(data["url"]).strip()
        raise RuntimeError(f"Unexpected part URL response: {data!r}")

    def complete_upload_session(self, upload_id: str, parts: List[dict]) -> dict:
        encoded = quote(str(upload_id), safe="")
        return self._request(
            "PATCH",
            f"/media/uploads/{encoded}",
            json={"parts": parts},
            timeout=self.upload_timeout,
        )

    def delete_media(self, media_uuid: str) -> None:
        """Soft-delete media from vault (does not affect already-sent copies)."""
        self._request("DELETE", f"/media/{media_uuid}")

    def upload_file_to_vault(
        self,
        file_path: str,
        *,
        name: Optional[str] = None,
        caption: Optional[str] = None,
        recommended_price_cents: Optional[int] = None,
        folder_name: Optional[str] = None,
        media_type: str = "image",
        strip_ai_metadata: bool = True,
    ) -> dict:
        """
        Full multipart upload → optional metadata → optional vault folder.

        For images, strip_ai_metadata=True re-encodes JPEG to drop C2PA /
        Content Credentials that Fanvue otherwise labels as "modified by AI".

        Returns dict with mediaUuid, status, folder, path, stripped.
        """
        import os

        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(file_path)

        upload_path = path
        stripped = False
        tmp_to_delete: Optional[str] = None
        if media_type == "image" and strip_ai_metadata:
            from utils.strip_c2pa import strip_to_temp_jpeg

            # Never fall back to the original: WaveSpeed JPEGs carry C2PA and
            # Fanvue will label them "modified by AI".
            tmp_to_delete, stripped = strip_to_temp_jpeg(path)
            upload_path = Path(tmp_to_delete)

        try:
            size = upload_path.stat().st_size
            display_name = (name or path.stem)[:255]
            # Keep a .jpg filename for Fanvue when we re-encoded
            upload_filename = (
                path.with_suffix(".jpg").name if stripped else path.name
            )
            session = self.create_upload_session(
                name=display_name,
                filename=upload_filename,
                media_type=media_type,
                size_bytes=size,
            )
            media_uuid = session["mediaUuid"]
            upload_id = session["uploadId"]
            part_size = int(session["partSize"])
            total_parts = session.get("totalParts")
            if not total_parts:
                total_parts = max(1, math.ceil(size / part_size))

            parts_meta: List[dict] = []
            with upload_path.open("rb") as fh:
                for part_number in range(1, int(total_parts) + 1):
                    chunk = fh.read(part_size)
                    if not chunk:
                        break
                    signed_url = self.get_upload_part_url(upload_id, part_number)
                    put = requests.put(
                        signed_url,
                        data=chunk,
                        headers={"Content-Type": "application/octet-stream"},
                        timeout=self.upload_timeout,
                    )
                    put.raise_for_status()
                    etag = put.headers.get("ETag") or put.headers.get("etag") or ""
                    etag = etag.strip()
                    part = {"PartNumber": part_number}
                    if etag:
                        part["ETag"] = etag
                    parts_meta.append(part)

            complete = self.complete_upload_session(upload_id, parts_meta)
            status = complete.get("status", "processing")

            if name is not None or caption is not None or recommended_price_cents is not None:
                try:
                    self.update_media_metadata(
                        media_uuid,
                        name=display_name,
                        caption=caption,
                        recommended_price_cents=recommended_price_cents,
                    )
                except Exception:
                    pass

            if folder_name:
                self.ensure_vault_folder(folder_name)
                self.attach_media_to_folder(folder_name, [media_uuid])

            return {
                "mediaUuid": media_uuid,
                "status": status,
                "folder": folder_name,
                "path": str(path),
                "name": display_name,
                "stripped": stripped,
            }
        finally:
            if tmp_to_delete:
                try:
                    os.unlink(tmp_to_delete)
                except OSError:
                    pass


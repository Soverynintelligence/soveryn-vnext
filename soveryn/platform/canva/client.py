"""Thin Canva Connect REST client for Eve marketing."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from soveryn.platform.canva.config import API_BASE, CanvaConfig, load_config
from soveryn.platform.canva.oauth import CanvaAuthError, get_access_token

logger = logging.getLogger("soveryn.platform.canva.client")


class CanvaAPIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _request(
    method: str,
    path: str,
    *,
    config: CanvaConfig | None = None,
    json_body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    token = get_access_token(cfg)
    url = f"{API_BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:800]
        try:
            body = json.loads(err)
        except json.JSONDecodeError:
            body = err
        raise CanvaAPIError(
            f"Canva {method} {path} HTTP {e.code}: {err}",
            status=e.code,
            body=body,
        ) from e
    except CanvaAuthError:
        raise
    except Exception as e:
        raise CanvaAPIError(f"Canva {method} {path} failed: {e}") from e


def create_ig_design(
    *,
    title: str,
    width: int = 1080,
    height: int = 1080,
    asset_id: str | None = None,
    config: CanvaConfig | None = None,
) -> dict[str, Any]:
    """Create IG-sized design. Pass asset_id or the canvas is blank."""
    payload: dict[str, Any] = {
        "design_type": {
            "type": "custom",
            "width": int(width),
            "height": int(height),
        },
        "title": (title or "SOVERYN post")[:200],
    }
    if asset_id:
        payload["asset_id"] = asset_id
    return _request("POST", "/designs", config=config, json_body=payload)


def upload_image_asset(
    path: Path | str,
    *,
    name: str | None = None,
    config: CanvaConfig | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Upload a local image to Canva Projects; return asset metadata."""
    import base64

    cfg = config or load_config()
    path = Path(path)
    if not path.is_file():
        raise CanvaAPIError(f"image not found: {path}")
    name = name or path.name
    name_b64 = base64.b64encode(name.encode("utf-8")).decode("ascii")
    token = get_access_token(cfg)
    data = path.read_bytes()
    req = urllib.request.Request(
        f"{API_BASE}/asset-uploads",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Asset-Upload-Metadata": json.dumps({"name_base64": name_b64}),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            created = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:800]
        raise CanvaAPIError(f"asset upload HTTP {e.code}: {err}", status=e.code) from e

    job = created.get("job") or created
    job_id = job.get("id")
    if not job_id:
        raise CanvaAPIError(f"asset upload missing job id: {created}")

    # May already be success
    if (job.get("status") or "").lower() == "success" and job.get("asset"):
        asset = job["asset"]
        return {"ok": True, "asset_id": asset.get("id"), "asset": asset, "job_id": job_id}

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        resp = _request("GET", f"/asset-uploads/{job_id}", config=cfg)
        job = resp.get("job") or resp
        status = (job.get("status") or "").lower()
        if status == "success":
            asset = job.get("asset") or {}
            return {
                "ok": True,
                "asset_id": asset.get("id"),
                "asset": asset,
                "job_id": job_id,
            }
        if status == "failed":
            raise CanvaAPIError(f"asset upload failed: {job.get('error') or job}")
        time.sleep(1.5)
    raise CanvaAPIError(f"asset upload timed out after {timeout_seconds}s")


def make_design_from_image(
    path: Path | str,
    *,
    title: str,
    width: int = 1080,
    height: int = 1080,
    config: CanvaConfig | None = None,
) -> dict[str, Any]:
    """Upload image → create IG design with that asset (not blank)."""
    cfg = config or load_config()
    up = upload_image_asset(path, name=Path(path).name, config=cfg)
    asset_id = up.get("asset_id")
    if not asset_id:
        raise CanvaAPIError(f"upload returned no asset_id: {up}")
    raw = create_ig_design(
        title=title, width=width, height=height, asset_id=asset_id, config=cfg
    )
    design = raw.get("design") or raw
    urls = design.get("urls") or {}
    return {
        "ok": True,
        "design_id": design.get("id"),
        "edit_url": urls.get("edit_url") or design.get("url"),
        "title": design.get("title"),
        "asset_id": asset_id,
        "thumbnail": (design.get("thumbnail") or {}).get("url"),
    }


def list_brand_templates(
    *,
    query: str | None = None,
    config: CanvaConfig | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    q: dict[str, str] = {"limit": str(max(1, min(int(limit), 50)))}
    if query:
        q["query"] = query
    return _request("GET", "/brand-templates", config=config, query=q)


def create_autofill_job(
    *,
    brand_template_id: str,
    data: dict[str, Any],
    title: str | None = None,
    config: CanvaConfig | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "brand_template_id": brand_template_id,
        "data": data,
    }
    if title:
        body["title"] = title[:200]
    return _request("POST", "/autofills", config=config, json_body=body)


def get_autofill_job(
    job_id: str, *, config: CanvaConfig | None = None
) -> dict[str, Any]:
    return _request("GET", f"/autofills/{job_id}", config=config)


def wait_autofill(
    job_id: str,
    *,
    config: CanvaConfig | None = None,
    timeout_seconds: float = 120.0,
    poll_seconds: float = 2.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        resp = get_autofill_job(job_id, config=config)
        job = resp.get("job") or resp
        status = (job.get("status") or "").lower()
        if status == "success":
            return job
        if status == "failed":
            raise CanvaAPIError(f"autofill failed: {job.get('error') or job}")
        time.sleep(poll_seconds)
    raise CanvaAPIError(f"autofill timed out after {timeout_seconds}s")


def create_export_job(
    *,
    design_id: str,
    format_type: str = "png",
    config: CanvaConfig | None = None,
) -> dict[str, Any]:
    fmt: dict[str, Any]
    if format_type == "png":
        fmt = {"type": "png", "export_quality": "regular"}
    elif format_type == "jpg":
        fmt = {"type": "jpg", "quality": 90, "export_quality": "regular"}
    elif format_type == "mp4":
        fmt = {
            "type": "mp4",
            "quality": "vertical_1080p",
            "export_quality": "regular",
        }
    else:
        raise CanvaAPIError(f"unsupported export format: {format_type}")
    return _request(
        "POST",
        "/exports",
        config=config,
        json_body={"design_id": design_id, "format": fmt},
    )


def get_export_job(
    job_id: str, *, config: CanvaConfig | None = None
) -> dict[str, Any]:
    return _request("GET", f"/exports/{job_id}", config=config)


def wait_export(
    job_id: str,
    *,
    config: CanvaConfig | None = None,
    timeout_seconds: float = 180.0,
    poll_seconds: float = 2.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        resp = get_export_job(job_id, config=config)
        job = resp.get("job") or resp
        status = (job.get("status") or "").lower()
        if status == "success":
            return job
        if status == "failed":
            raise CanvaAPIError(f"export failed: {job.get('error') or job}")
        time.sleep(poll_seconds)
    raise CanvaAPIError(f"export timed out after {timeout_seconds}s")


def download_export_to_media(
    urls: list[str],
    *,
    config: CanvaConfig | None = None,
    stem: str | None = None,
) -> list[Path]:
    cfg = config or load_config()
    cfg.media_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or uuid4().hex[:12]
    out: list[Path] = []
    for i, url in enumerate(urls):
        suffix = ".png"
        lower = url.lower()
        if ".jpg" in lower or "jpeg" in lower:
            suffix = ".jpg"
        elif ".mp4" in lower:
            suffix = ".mp4"
        path = cfg.media_dir / f"{stem}_{i}{suffix}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
        out.append(path)
    return out


def export_design_to_media(
    design_id: str,
    *,
    format_type: str = "png",
    config: CanvaConfig | None = None,
    stem: str | None = None,
) -> dict[str, Any]:
    """Create export job, wait, download into data/media/canva/."""
    cfg = config or load_config()
    created = create_export_job(
        design_id=design_id, format_type=format_type, config=cfg
    )
    job = created.get("job") or created
    job_id = job.get("id")
    if not job_id:
        raise CanvaAPIError(f"export create missing job id: {created}")
    done = wait_export(str(job_id), config=cfg)
    urls = list(done.get("urls") or [])
    if not urls:
        raise CanvaAPIError(f"export succeeded but no urls: {done}")
    paths = download_export_to_media(urls, config=cfg, stem=stem or design_id)
    return {
        "ok": True,
        "design_id": design_id,
        "export_job_id": job_id,
        "paths": [str(p) for p in paths],
        "path": str(paths[0]),
    }


def autofill_and_wait(
    *,
    brand_template_id: str,
    fields: dict[str, str],
    title: str | None = None,
    config: CanvaConfig | None = None,
) -> dict[str, Any]:
    """Autofill text fields (type=text) and return design metadata."""
    data = {
        key: {"type": "text", "text": value}
        for key, value in fields.items()
        if value is not None
    }
    created = create_autofill_job(
        brand_template_id=brand_template_id,
        data=data,
        title=title,
        config=config,
    )
    job = created.get("job") or created
    job_id = job.get("id")
    if not job_id:
        raise CanvaAPIError(f"autofill create missing job id: {created}")
    # May already be complete
    status = (job.get("status") or "").lower()
    if status != "success":
        job = wait_autofill(str(job_id), config=config)
    result = job.get("result") or {}
    design = result.get("design") or {}
    return {
        "ok": True,
        "job_id": job_id,
        "design_id": design.get("id"),
        "edit_url": design.get("url"),
        "title": design.get("title"),
        "thumbnail": (design.get("thumbnail") or {}).get("url"),
    }

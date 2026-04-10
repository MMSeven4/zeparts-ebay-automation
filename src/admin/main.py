"""Production FastAPI admin panel for ZEParts eBay automation."""

from __future__ import annotations

from datetime import datetime
import pathlib

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.catalog.ingestion import ingest_single_sku
from src.db.models import ListingStatus, SyncAction
from src.db.repository import ListingRepository
from src.ebay.trading_api import EbayTradingClient

BASE_DIR = pathlib.Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="ZEParts Admin Panel")

static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _format_datetime(value: datetime | None) -> str:
    """Format datetimes for the admin UI."""

    if value is None:
        return "Never"
    return value.strftime("%b %d, %Y %H:%M")


def _status_badge_class(status: ListingStatus | str) -> str:
    """Return the CSS badge class for a listing status."""

    status_value = status.value if hasattr(status, "value") else str(status)
    return {
        "active": "badge-active",
        "ended": "badge-ended",
        "error": "badge-error",
        "pending": "badge-pending",
    }.get(status_value, "badge-pending")


templates.env.filters["datetime"] = _format_datetime
templates.env.globals["status_badge_class"] = _status_badge_class


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect the admin root to the listings page."""

    return RedirectResponse(url="/listings", status_code=302)


@app.get("/listings", response_class=HTMLResponse)
async def listings(request: Request) -> HTMLResponse:
    """Render the main listings overview page."""

    repo = ListingRepository()
    all_listings = await repo.get_all_listings()
    counts = {
        "total": len(all_listings),
        "active": sum(1 for listing in all_listings if listing.status == ListingStatus.active),
        "ended": sum(1 for listing in all_listings if listing.status == ListingStatus.ended),
        "error": sum(1 for listing in all_listings if listing.status == ListingStatus.error),
    }
    return templates.TemplateResponse(
        name="listings.html",
        request=request,
        context={
            "request": request,
            "page_title": "Listings",
            "listings": all_listings,
            "counts": counts,
        },
    )


@app.get("/listings/{sku}", response_class=HTMLResponse)
async def listing_detail(request: Request, sku: str) -> HTMLResponse:
    """Render the detail page for a single SKU."""

    repo = ListingRepository()
    listing = await repo.get_by_sku(sku)
    if listing is None:
        raise HTTPException(status_code=404, detail="listing not found")

    sync_logs = await repo.get_sync_logs(sku, limit=10)
    return templates.TemplateResponse(
        name="listing_detail.html",
        request=request,
        context={
            "request": request,
            "page_title": f"Listing {sku}",
            "listing": listing,
            "sync_logs": sync_logs,
        },
    )


@app.post("/listings/{sku}/sync")
async def trigger_sync(sku: str) -> RedirectResponse:
    """Trigger a manual sync for the given SKU."""

    await ingest_single_sku(sku, dry_run=False)
    return RedirectResponse(url=f"/listings/{sku}", status_code=303)


@app.post("/listings/{sku}/end")
async def end_listing(sku: str) -> RedirectResponse:
    """End the eBay listing for the given SKU and update DB state."""

    repo = ListingRepository()
    listing = await repo.get_by_sku(sku)
    if listing is None:
        raise HTTPException(status_code=404, detail="listing not found")
    if not listing.ebay_item_id:
        raise HTTPException(status_code=400, detail="listing has no eBay item id")

    await EbayTradingClient().end_item(listing.ebay_item_id)
    await repo.update_status(sku, ListingStatus.ended)
    await repo.log_sync_action(
        sku=sku,
        action=SyncAction.end,
        success=True,
        ebay_item_id=listing.ebay_item_id,
        detail="Listing ended from admin panel",
    )
    return RedirectResponse(url="/listings", status_code=303)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a simple health response for monitoring."""

    return {"status": "healthy"}

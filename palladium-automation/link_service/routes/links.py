from fastapi import APIRouter
from pydantic import BaseModel
from link_service.db import models

router = APIRouter(prefix="/links", tags=["links"])

class AddLinksRequest(BaseModel):
    user_id: str
    links: list[str]

@router.post("/add")
async def add_links_endpoint(request: AddLinksRequest):
    models.add_links(request.user_id, request.links)
    return {"status": "success", "message": f"Added {len(request.links)} links."}

@router.get("/active/{user_id}")
async def get_active_links_endpoint(user_id: str):
    links = models.get_active_links(user_id)
    if not links:
        return {
            "links": [],
            "message": "ALL_LINKS_FLAGGED"
        }
    return {"links": links}

@router.get("/next/{user_id}")
async def get_next_link_endpoint(user_id: str):
    url = models.get_next_active_link(user_id)
    if not url:
        return {
            "url": None,
            "message": "NO_ACTIVE_LINKS"
        }
    return {"url": url}

@router.get("/all/{user_id}")
async def get_all_links_endpoint(user_id: str):
    links = models.get_all_links(user_id)
    return {"links": links}
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..retrieval import RetrievalError, get_knowledge_base

logger = logging.getLogger("triage.kb")
router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])


@router.get("/search")
def search_kb(
    q: str = Query(..., min_length=2),
    equipment_type: Optional[str] = None,
    limit: int = Query(5, ge=1, le=20),
):
    try:
        kb = get_knowledge_base()
        hits = kb.search(q, equipment_type=equipment_type, top_k=limit)
    except RetrievalError as exc:
        logger.error("Retrieval failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"code": "retrieval_failed", "message": str(exc)},
        )
    return {
        "query": q,
        "equipment_type": equipment_type,
        "count": len(hits),
        "hits": [
            {
                "id": h.chunk.id,
                "title": h.chunk.title,
                "equipment_type": h.chunk.equipment_type,
                "source": h.chunk.source,
                "score": h.score,
                "text": h.chunk.text,
            }
            for h in hits
        ],
    }

---
name: api-design
description: FastAPI best practices for RESTful API design, routing, and middleware
triggers: [api, endpoint, route, rest, fastapi, design]
---

# API Design Skill

When designing or generating API endpoints, follow these conventions:

1. **Routing**: Use APIRouter with prefix and tags for grouping
2. **Validation**: Use Pydantic v2 models for request/response validation
3. **Error Handling**: Use HTTPException with proper status codes
4. **Async**: Use async def for I/O-bound operations
5. **Dependency Injection**: Use FastAPI Depends() for shared resources
6. **Documentation**: Every endpoint must have a docstring and response model

## FastAPI Patterns

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["items"])

@router.post("/items", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate):
    """Create a new item."""
    ...

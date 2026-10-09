import asyncio
from typing import Annotated, Any, Literal, cast
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from vasa.contracts.models import TenantContext
from vasa.control.auth import require_context, require_csrf
from vasa.knowledge.service import KnowledgeService
from vasa.storage.calls import CallRecord, CallRepository
from vasa.storage.models import Agent, Tenant


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


router = APIRouter(prefix="/api", dependencies=[Depends(no_store)])
Authenticated = Annotated[TenantContext, Depends(require_context)]
Mutation = Annotated[TenantContext, Depends(require_csrf)]


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    business_name: str = Field(default="", max_length=200)
    greeting: str = Field(default="Hello, how can I help?", max_length=1000)
    business_description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="Never invent business facts.", max_length=2000)
    language: Literal["en"] = "en"
    voice: Literal["kokoro_af_maple"] = "kokoro_af_maple"

    @field_validator("name", "business_name", "greeting", "business_description", "instructions")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("invalid text")
        value.encode("utf-8")
        return value.strip()

    @model_validator(mode="after")
    def prompt_bounds(self) -> "AgentInput":
        if (
            not self.name
            or sum(
                len(value)
                for value in (
                    self.name,
                    self.business_name,
                    self.business_description,
                    self.instructions,
                )
            )
            > 3600
        ):
            raise ValueError("agent instruction capacity exceeded")
        return self


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100000)


def agent_payload(agent: Agent | None) -> dict[str, Any]:
    if agent is None:
        return AgentInput(name="Assistant").model_dump()
    return {key: getattr(agent, key) for key in AgentInput.model_fields}


def call_payload(record: CallRecord) -> dict[str, Any]:
    return {
        key: getattr(record, key)
        for key in ("id", "caller", "started_at", "ended_at", "state", "summary", "outcome")
    }


@router.get("/agent")
async def get_agent(request: Request, context: Authenticated) -> dict[str, Any]:
    try:
        async with request.app.state.database.session() as session:
            agent = await session.scalar(
                select(Agent)
                .where(Agent.tenant_id == context.tenant_id)
                .order_by(Agent.id)
                .limit(1)
            )
            return agent_payload(agent)
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None


@router.put("/agent")
async def put_agent(body: AgentInput, request: Request, context: Mutation) -> dict[str, Any]:
    try:
        async with request.app.state.database.session() as session, session.begin():
            tenant = await session.scalar(
                select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
            )
            if tenant is None:
                raise HTTPException(401, "authentication_required")
            agent = await session.scalar(
                select(Agent)
                .where(Agent.tenant_id == context.tenant_id)
                .order_by(Agent.id)
                .limit(1)
            )
            if agent is None:
                agent = Agent(tenant_id=context.tenant_id, **body.model_dump())
                session.add(agent)
            else:
                for key, value in body.model_dump().items():
                    setattr(agent, key, value)
            await session.flush()
            return agent_payload(agent)
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None


def knowledge(request: Request) -> KnowledgeService:
    return cast(KnowledgeService, request.app.state.knowledge)


def source_payload(source: object) -> dict[str, Any]:
    return {
        key: getattr(source, key) for key in ("id", "name", "kind", "created_at", "chunk_count")
    }


@router.get("/knowledge")
async def sources(request: Request, context: Authenticated) -> dict[str, Any]:
    try:
        return {
            "sources": [
                source_payload(source) for source in await knowledge(request).list_sources(context)
            ]
        }
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None


async def ingest(
    request: Request, context: TenantContext, name: str, content: str | bytes
) -> dict[str, Any]:
    try:
        async with asyncio.timeout(30):
            if isinstance(content, str):
                source = await knowledge(request).add_text(context, name, content)
            else:
                source = await knowledge(request).add_document(context, name, content)
        return source_payload(source)
    except (ValueError, UnicodeError):
        raise HTTPException(422, "invalid_document") from None
    except Exception:
        raise HTTPException(503, "unavailable") from None


@router.post("/knowledge", status_code=201)
async def add_text(body: KnowledgeInput, request: Request, context: Mutation) -> dict[str, Any]:
    return await ingest(request, context, body.name, body.text)


@router.post("/knowledge/upload", status_code=201)
async def upload(request: Request, context: Mutation) -> dict[str, Any]:
    name = unquote(request.headers.get("x-file-name", ""))
    body = await request.body()
    if not body or len(body) > 2 * 1024 * 1024:
        raise HTTPException(413, "request_too_large")
    return await ingest(request, context, name, body)


@router.delete("/knowledge/{source_id}")
async def delete_source(source_id: UUID, request: Request, context: Mutation) -> dict[str, str]:
    try:
        if not await knowledge(request).delete_source(context, source_id):
            raise HTTPException(404, "not_found")
        return {"status": "deleted"}
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None


@router.get("/calls")
async def calls(
    request: Request, context: Authenticated, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    try:
        async with request.app.state.database.session() as session:
            records = await CallRepository(session, context).list(limit=limit, offset=offset)
        return {"calls": [call_payload(record) for record in records]}
    except ValueError:
        raise HTTPException(422, "invalid_pagination") from None
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None


@router.get("/calls/{call_id}")
async def call_detail(
    call_id: UUID,
    request: Request,
    context: Authenticated,
    after_sequence: int = 0,
    tool_offset: int = 0,
) -> dict[str, Any]:
    try:
        async with request.app.state.database.session() as session:
            repo = CallRepository(session, context)
            record = await repo.get(call_id)
            if record is None:
                raise HTTPException(404, "not_found")
            messages = await repo.messages(call_id, after_sequence=after_sequence)
            executions = await repo.tool_calls(call_id, offset=tool_offset)
        return {
            "call": call_payload(record),
            "messages": [
                {key: getattr(message, key) for key in ("sequence", "role", "content")}
                for message in messages
            ],
            "tool_calls": [
                {key: getattr(execution, key) for key in ("id", "name", "status", "error_code")}
                for execution in executions
            ],
            "next_sequence": messages[-1].sequence
            if messages and messages[-1].sequence < record.message_sequence
            else None,
            "next_tool_offset": tool_offset + 100
            if len(executions) == 100 and tool_offset < 100
            else None,
        }
    except ValueError:
        raise HTTPException(422, "invalid_pagination") from None
    except SQLAlchemyError:
        raise HTTPException(503, "unavailable") from None

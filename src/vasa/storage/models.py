from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    greeting: Mapped[str] = mapped_column(
        String(1000), default="Hello, how can I help?", server_default="Hello, how can I help?"
    )
    business_description: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    instructions: Mapped[str] = mapped_column(
        String(2000),
        default="Never invent business facts.",
        server_default="Never invent business facts.",
    )
    language: Mapped[str] = mapped_column(String(10), default="en", server_default="en")
    voice: Mapped[str] = mapped_column(
        String(40), default="ljspeech_en", server_default="ljspeech_en"
    )

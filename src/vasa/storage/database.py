from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    """Own a bounded reusable connection pool; callers own session transactions."""

    def __init__(self, url: str, *, timeout_seconds: float = 3.0) -> None:
        if not 0 < timeout_seconds <= 30:
            raise ValueError("database timeout must be between zero and 30 seconds")
        self.engine = create_async_engine(
            url,
            pool_size=5,
            max_overflow=5,
            pool_timeout=timeout_seconds,
            pool_pre_ping=True,
            connect_args={
                "timeout": timeout_seconds,
                "command_timeout": timeout_seconds,
                "server_settings": {"statement_timeout": str(int(timeout_seconds * 1000))},
            },
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        return self._sessions()

    async def aclose(self) -> None:
        await self.engine.dispose()

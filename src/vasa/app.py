from fastapi import FastAPI

from vasa.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="VASA", version="0.1.0")

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    return app


app = create_app()

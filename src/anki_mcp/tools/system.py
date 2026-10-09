from mcp.server import MCPServer

from anki_mcp.state import Ctx, state
from anki_mcp.tools.annotations import SYNC


async def sync(ctx: Ctx) -> str:
    """Sync the collection with AnkiWeb so new cards reach the user's phone."""
    await state(ctx).anki.invoke("sync", timeout=120)
    return "Sync started."


def register(mcp: MCPServer) -> None:
    mcp.add_tool(
        sync, title="Sync with AnkiWeb", annotations=SYNC, structured_output=False
    )

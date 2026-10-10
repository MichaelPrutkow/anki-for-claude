def main() -> None:
    from anki_mcp import collection, drafts, images, stats, youtube  # noqa: F401  importing registers the tools
    from anki_mcp.server import mcp

    mcp.run()

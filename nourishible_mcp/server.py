from __future__ import annotations
from mcp.server import MCPServer

from . import local


mcp = MCPServer(
    "Nourishible Local",
    instructions=(
        "Local recipe-source extraction for Nourishible. Read the nourishible://recipe-workflow "
        "resource before structuring a recipe. Saving remains on the hosted Nourishible MCP so OAuth "
        "credentials never enter this local process."
    ),
)


@mcp.resource("nourishible://recipe-workflow", name="Recipe extraction workflow")
def recipe_workflow() -> str:
    """The complete, bundled recipe-nourishible workflow and schema."""
    return local.workflow_text()


@mcp.prompt(name="recipe_nourishible")
def recipe_nourishible_prompt(source_url: str) -> str:
    """Extract and save a recipe from a supported cooking-video URL."""
    return (
        f"Extract the cooking recipe at {source_url} and save it to my Nourishible account. "
        "Read nourishible://recipe-workflow first, use this server's local extraction tools, "
        "inspect all returned frames, and use the hosted Nourishible MCP tools for deduplication, "
        "saving, and thumbnail upload."
    )


@mcp.tool()
def recipe_setup_status(profile: str = "standard") -> dict:
    """Check local recipe extraction dependencies. Profile is standard or instagram."""
    return local.setup_status(profile)


@mcp.tool()
def install_recipe_dependencies(profile: str = "standard") -> dict:
    """Install missing local extraction dependencies. May invoke Homebrew; use only at the user's request."""
    return local.install_dependencies(profile)


@mcp.tool()
def extract_recipe_evidence(
    source_url: str,
    detail: str = "balanced",
    resolution: int = 1024,
    max_frames: int | None = None,
    start: str | None = None,
    end: str | None = None,
    section: str | None = None,
    timestamps: str | None = None,
    out_dir: str | None = None,
    no_whisper: bool = False,
) -> dict:
    """Download a YouTube/XHS source and return transcript/report plus absolute local frame paths."""
    return local.extract_evidence(
        source_url, detail, resolution, max_frames, start, end, section, timestamps, out_dir, no_whisper
    )


@mcp.tool()
def instagram_capture_instructions(
    source_url: str, seconds: int = 45, out_dir: str | None = None
) -> dict:
    """Return the bundled human-confirmed Instagram capture command; never navigates or starts playback."""
    return local.instagram_capture_instructions(source_url, seconds, out_dir)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

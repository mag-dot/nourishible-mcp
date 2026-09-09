import unittest

import anyio
from mcp import Client

from nourishible_mcp.server import mcp


class McpSurfaceTests(unittest.TestCase):
    def test_tools_resource_and_prompt_are_discoverable(self):
        async def inspect_surface():
            async with Client(mcp) as client:
                tools = await client.list_tools()
                resources = await client.list_resources()
                prompts = await client.list_prompts()
                return (
                    {tool.name for tool in tools.tools},
                    {str(resource.uri) for resource in resources.resources},
                    {prompt.name for prompt in prompts.prompts},
                )

        tools, resources, prompts = anyio.run(inspect_surface)
        self.assertEqual(
            {
                "recipe_setup_status",
                "install_recipe_dependencies",
                "extract_recipe_evidence",
                "instagram_capture_instructions",
            },
            tools,
        )
        self.assertIn("nourishible://recipe-workflow", resources)
        self.assertIn("recipe_nourishible", prompts)


if __name__ == "__main__":
    unittest.main()


import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import * as api from "./api.js";
import { NotAuthenticatedError } from "./api.js";

// Recipe input shape mirrors backend/src/recipes/schema.ts, which mirrors
// docs/PRODUCT-STRATEGY.md §4.5. Kept in sync by hand for now — small enough
// surface that a shared package would be more ceremony than value.
const ingredientShape = z.object({
  rawText: z.string(),
  quantity: z.number().nullable().default(null),
  unit: z.string().nullable().default(null),
  name: z.string(),
  optional: z.boolean().default(false),
  category: z.enum(["produce", "protein", "dairy", "pantry", "other"]).nullable().default(null),
});

const stepShape = z.object({
  text: z.string(),
  timestampSeconds: z.number().nullable().default(null),
});

// Shared by save_recipe (title required) and update_recipe (title optional,
// PUT-style partial update — omitted keys are left untouched server-side).
// Kept as one object so the two tools can't silently drift apart.
const recipeOptionalFields = {
  sourceUrl: z.string().url().nullable().optional(),
  sourcePlatform: z.enum(["instagram", "youtube", "manual"]).optional(),
  creatorHandle: z.string().nullable().optional(),
  thumbnailUrl: z.string().url().nullable().optional(),
  servings: z.number().int().positive().nullable().optional(),
  totalTimeMinutes: z.number().int().positive().nullable().optional(),
  ingredients: z.array(ingredientShape).optional(),
  steps: z.array(stepShape).optional(),
  tags: z.array(z.string()).optional(),
  notes: z.string().nullable().optional(),
  confidence: z.record(z.string(), z.enum(["high", "medium", "low"])).optional(),
};

function errorResult(err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

export function buildServer(): McpServer {
  const server = new McpServer({ name: "nourishible", version: "1.0.0" });

  // Public reads — no connection needed, work before Step 6.5's "connect
  // nourishible" step. Same tool names/scope as the hosted remote MCP server
  // (backend/src/mcp/tools.ts in the private repo) so a skill's instructions
  // don't have to branch on which connector is active.
  server.registerTool(
    "search_recipes",
    {
      title: "Search nourishible's public recipes",
      description:
        "List recipes across every nourishible user's public library, newest first, optionally filtered by a " +
        "search term matched against title/tags. No account or sign-in needed — this is public data. Doesn't " +
        "tell you who saved a recipe, only that it exists and its content. Use save_recipe/list_my_recipes " +
        "(both require you to be connected) to work with your own account's recipes instead.",
      inputSchema: { query: z.string().optional() },
    },
    async ({ query }) => {
      try {
        const { recipes } = await api.searchRecipes(query);
        return { content: [{ type: "text", text: JSON.stringify(recipes, null, 2) }] };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  server.registerTool(
    "get_recipe",
    {
      title: "Get a public recipe",
      description: "Fetch one recipe by id or slug from nourishible's public catalog — any user's, no connection needed.",
      inputSchema: { idOrSlug: z.string() },
    },
    async ({ idOrSlug }) => {
      try {
        const recipe = await api.getCommunityRecipe(idOrSlug);
        if (!recipe) return { content: [{ type: "text", text: `No recipe found with id/slug ${idOrSlug}.` }], isError: true };
        return { content: [{ type: "text", text: JSON.stringify(recipe, null, 2) }] };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  // Authenticated — the connected account's own library.
  server.registerTool(
    "list_my_recipes",
    {
      title: "List my saved recipes",
      description:
        "List recipes in your own nourishible library (the account this connector is logged in as), optionally " +
        "filtered by a search term matched against title/tags. Use this — not search_recipes — for dedup checks " +
        "(\"have I already saved this video\") since search_recipes doesn't reveal ownership.",
      inputSchema: { query: z.string().optional() },
    },
    async ({ query }) => {
      try {
        const { recipes } = await api.listMyRecipes(query);
        return { content: [{ type: "text", text: JSON.stringify(recipes, null, 2) }] };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  server.registerTool(
    "get_my_recipe",
    {
      title: "Get one of my saved recipes",
      description: "Fetch one recipe from your own nourishible library by id.",
      inputSchema: { id: z.string() },
    },
    async ({ id }) => {
      try {
        const recipe = await api.getMyRecipe(id);
        if (!recipe) return { content: [{ type: "text", text: `No recipe found with id ${id}.` }], isError: true };
        return { content: [{ type: "text", text: JSON.stringify(recipe, null, 2) }] };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  server.registerTool(
    "save_recipe",
    {
      title: "Save a recipe to nourishible",
      description:
        "Save a structured recipe (that you've already extracted from a video, or written by hand) into your " +
        "own nourishible library. Use this after producing a recipe JSON — e.g. following the same " +
        "reconcile-and-structure approach as this repo's skills/recipe-nourishible/SKILL.md: read on-screen " +
        "text, transcript, and caption, prefer on-screen text on conflicts, match key moments to steps via " +
        "timestampSeconds when you can pin them, and note anything uncertain in confidence/notes rather than " +
        "guessing silently.",
      inputSchema: { title: z.string(), ...recipeOptionalFields },
    },
    async (recipe) => {
      try {
        const saved = await api.saveRecipe(recipe as Record<string, unknown>);
        return { content: [{ type: "text", text: JSON.stringify(saved, null, 2) }] };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  server.registerTool(
    "update_recipe",
    {
      title: "Update a saved recipe",
      description:
        "Change one or more fields on a recipe already in the user's nourishible library. Only pass the fields " +
        "you want to change — anything you omit is left exactly as it was (this is a partial update, not a " +
        "full replace). Use this instead of delete_recipe + save_recipe when fixing a mistake, since delete+ " +
        "recreate loses the recipe's id/slug/share link.",
      inputSchema: { id: z.string(), title: z.string().optional(), ...recipeOptionalFields },
    },
    async ({ id, ...updates }) => {
      try {
        const updated = await api.updateRecipe(id, updates as Record<string, unknown>);
        if (!updated) return { content: [{ type: "text", text: `No recipe found with id ${id}.` }], isError: true };
        return { content: [{ type: "text", text: JSON.stringify(updated, null, 2) }] };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  server.registerTool(
    "set_recipe_thumbnail",
    {
      title: "Set a recipe's thumbnail image",
      description:
        "Upload a local JPEG file as a recipe's thumbnail — e.g. the #1-ranked frame picked by " +
        "skills/recipe-nourishible/SKILL.md's frame-selection step (finished-dish shot preferred; see that " +
        "skill's 'pick the best frames for preview thumbnails' section for the selection criteria). Pass the " +
        "local filesystem path to the JPEG, not the image bytes or a URL — this connector runs on your own " +
        "machine, so it reads the file itself. A recipe saved without this call will show with no thumbnail.",
      inputSchema: { id: z.string(), filePath: z.string() },
    },
    async ({ id, filePath }) => {
      try {
        const updated = await api.setRecipeThumbnail(id, filePath);
        if (!updated) return { content: [{ type: "text", text: `No recipe found with id ${id}.` }], isError: true };
        return { content: [{ type: "text", text: JSON.stringify(updated, null, 2) }] };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  server.registerTool(
    "delete_recipe",
    {
      title: "Delete a saved recipe",
      description: "Remove a recipe from the user's nourishible library by id.",
      inputSchema: { id: z.string() },
    },
    async ({ id }) => {
      try {
        const deleted = await api.deleteRecipe(id);
        return {
          content: [{ type: "text", text: deleted ? `Deleted ${id}.` : `No recipe found with id ${id}.` }],
          isError: !deleted,
        };
      } catch (err) {
        return errorResult(err);
      }
    }
  );

  return server;
}

export async function runServer(): Promise<void> {
  const server = buildServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("nourishible MCP server running on stdio.");
}

export { NotAuthenticatedError };

import { readFile, stat } from "node:fs/promises";
import { loadConfig, resolveApiBaseUrl } from "./config.js";

export class NotAuthenticatedError extends Error {
  constructor() {
    super(
      "Not connected to nourishible yet. Run `npx nourishible-mcp login` in a terminal " +
        "(you must already be signed in to nourishible in your browser), then retry."
    );
  }
}

async function call(pathAndQuery: string, init?: RequestInit): Promise<Response> {
  const config = loadConfig();
  if (!config) throw new NotAuthenticatedError();

  const res = await fetch(new URL(pathAndQuery, config.apiBaseUrl), {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${config.accessToken}`,
      "Content-Type": "application/json",
    },
  });

  if (res.status === 401) {
    throw new NotAuthenticatedError();
  }
  return res;
}

export async function listMyRecipes(query?: string) {
  const qs = query ? `?q=${encodeURIComponent(query)}` : "";
  const res = await call(`/recipes${qs}`);
  if (!res.ok) throw new Error(`list_my_recipes failed: ${res.status} ${await res.text()}`);
  return (await res.json()) as { recipes: unknown[] };
}

export async function getMyRecipe(id: string) {
  const res = await call(`/recipes/${encodeURIComponent(id)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`get_my_recipe failed: ${res.status} ${await res.text()}`);
  return await res.json();
}

// Public, unauthenticated reads across every nourishible user's library —
// same /recipes/community endpoint the website's community browse page
// uses. Deliberately a plain fetch with no auth header (config may not even
// exist yet if the caller hasn't connected an account): these two tools
// work before Step 6.5's "connect nourishible" step, unlike everything else
// in this file.
export async function searchRecipes(query?: string) {
  const qs = query ? `?q=${encodeURIComponent(query)}` : "";
  const res = await fetch(new URL(`/recipes/community${qs}`, resolveApiBaseUrl()));
  if (!res.ok) throw new Error(`search_recipes failed: ${res.status} ${await res.text()}`);
  return (await res.json()) as { recipes: unknown[] };
}

export async function getCommunityRecipe(idOrSlug: string) {
  const res = await fetch(new URL(`/recipes/community/${encodeURIComponent(idOrSlug)}`, resolveApiBaseUrl()));
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`get_recipe failed: ${res.status} ${await res.text()}`);
  return await res.json();
}

export async function saveRecipe(recipe: Record<string, unknown>) {
  const res = await call(`/recipes`, { method: "POST", body: JSON.stringify(recipe) });
  if (!res.ok) throw new Error(`save_recipe failed: ${res.status} ${await res.text()}`);
  return await res.json();
}

/** PUT /recipes/:id — only the keys present in `updates` are changed (matches the backend's partial-update semantics). */
export async function updateRecipe(id: string, updates: Record<string, unknown>) {
  const res = await call(`/recipes/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(updates) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`update_recipe failed: ${res.status} ${await res.text()}`);
  return await res.json();
}

export async function deleteRecipe(id: string) {
  const res = await call(`/recipes/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (res.status === 404) return false;
  if (!res.ok) throw new Error(`delete_recipe failed: ${res.status} ${await res.text()}`);
  return true;
}

// Backend's own cap (backend/src/recipes/routes.ts MAX_THUMBNAIL_BYTES) — checked
// here too so a too-large file fails with a clear local message instead of a
// generic HTTP error after the whole file has already been read into memory.
const MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024;
const JPEG_MAGIC = Buffer.from([0xff, 0xd8, 0xff]);

/**
 * POST /recipes/:id/thumbnail — uploads a local JPEG file as the recipe's
 * thumbnail. Takes a local file path rather than base64 in the tool call
 * itself: the calling agent already has the picked frame on disk (from
 * skills/recipe-extract/'s own frame-extraction step), and round-tripping
 * it through base64 in a tool-call argument would needlessly bloat the
 * agent's context for no benefit — this server runs locally, on the same
 * machine, so a plain path is the natural shape here. (A remote-hosted MCP
 * connector, if one exists in the future, would need a different shape —
 * see docs/PRODUCT-STRATEGY.md §3.11's open questions.)
 */
export async function setRecipeThumbnail(id: string, filePath: string) {
  let fileStat;
  try {
    fileStat = await stat(filePath);
  } catch {
    throw new Error(`set_recipe_thumbnail: no file found at "${filePath}".`);
  }
  if (fileStat.size === 0) {
    throw new Error(`set_recipe_thumbnail: "${filePath}" is empty.`);
  }
  if (fileStat.size > MAX_THUMBNAIL_BYTES) {
    throw new Error(
      `set_recipe_thumbnail: "${filePath}" is ${(fileStat.size / 1024 / 1024).toFixed(1)}MB, over the ${MAX_THUMBNAIL_BYTES / 1024 / 1024}MB limit.`
    );
  }

  const bytes = await readFile(filePath);
  if (!bytes.subarray(0, 3).equals(JPEG_MAGIC)) {
    throw new Error(`set_recipe_thumbnail: "${filePath}" doesn't look like a JPEG file.`);
  }

  const config = loadConfig();
  if (!config) throw new NotAuthenticatedError();

  const res = await fetch(new URL(`/recipes/${encodeURIComponent(id)}/thumbnail`, config.apiBaseUrl), {
    method: "POST",
    headers: { Authorization: `Bearer ${config.accessToken}`, "Content-Type": "image/jpeg" },
    body: new Uint8Array(bytes),
  });
  if (res.status === 401) throw new NotAuthenticatedError();
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`set_recipe_thumbnail failed: ${res.status} ${await res.text()}`);
  return await res.json();
}

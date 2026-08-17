import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Where the OAuth token this MCP server uses lives. One token per machine
// (not per-Claude-conversation) — same pattern as e.g. `gh auth login`.
const CONFIG_DIR = process.env.NOURISHIBLE_MCP_CONFIG_DIR ?? path.join(os.homedir(), ".nourishible-mcp");
const CONFIG_PATH = path.join(CONFIG_DIR, "config.json");

// The real, deployed backend — this is a public package now, so the default
// has to work for someone who never set up a local backend, unlike this
// repo's own dev convenience of defaulting to localhost. Override via
// NOURISHIBLE_API_URL for local development against `../backend` (see
// docs/PRODUCT-STRATEGY.md in the private nourishible-app repo).
export function resolveApiBaseUrl(): string {
  return process.env.NOURISHIBLE_API_URL ?? "https://backend-api-production-c967.up.railway.app";
}

export interface StoredConfig {
  accessToken: string;
  scope: string;
  obtainedAt: string;
  apiBaseUrl: string;
}

export function loadConfig(): StoredConfig | null {
  try {
    const raw = fs.readFileSync(CONFIG_PATH, "utf8");
    return JSON.parse(raw) as StoredConfig;
  } catch {
    return null;
  }
}

export function saveConfig(config: StoredConfig): void {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), { mode: 0o600 });
}

export function clearConfig(): void {
  try {
    fs.unlinkSync(CONFIG_PATH);
  } catch {
    // already gone
  }
}

export { CONFIG_PATH };

#!/usr/bin/env node
import "dotenv/config";
import { login, logout } from "./oauth-login.js";
import { runServer } from "./server.js";

const command = process.argv[2];

async function main() {
  if (command === "login") {
    await login();
    return;
  }
  if (command === "logout") {
    await logout();
    const { CONFIG_PATH } = await import("./config.js");
    console.error(`Removed stored credentials (${CONFIG_PATH}).`);
    return;
  }

  // Default (no args, or launched directly by Claude Desktop/Code as an MCP
  // server config entry): run the stdio MCP server.
  await runServer();
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});

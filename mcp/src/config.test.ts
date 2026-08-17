import { mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// config.ts reads NOURISHIBLE_MCP_CONFIG_DIR once, at module load, so each
// test gets its own temp dir AND a fresh module instance via vi.resetModules
// — reusing the cached module across tests would silently reuse whichever
// dir the first import saw.
let dir: string;
let mod: typeof import("./config.js");

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "nourishible-mcp-config-test-"));
  process.env.NOURISHIBLE_MCP_CONFIG_DIR = dir;
  vi.resetModules();
  mod = await import("./config.js");
});

afterEach(async () => {
  delete process.env.NOURISHIBLE_MCP_CONFIG_DIR;
  await rm(dir, { recursive: true, force: true });
});

const sample = {
  accessToken: "test-token-value",
  scope: "recipes:read recipes:write",
  obtainedAt: "2026-08-17T00:00:00.000Z",
  apiBaseUrl: "http://localhost:4000",
};

describe("loadConfig", () => {
  it("returns null when no config file exists", () => {
    expect(mod.loadConfig()).toBeNull();
  });

  it("returns null (not a throw) for a corrupt config file", async () => {
    const { writeFile, mkdir } = await import("node:fs/promises");
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, "config.json"), "{ not valid json", "utf8");
    expect(mod.loadConfig()).toBeNull();
  });
});

describe("saveConfig", () => {
  it("round-trips through loadConfig", () => {
    mod.saveConfig(sample);
    expect(mod.loadConfig()).toEqual(sample);
  });

  it("creates the config directory if it doesn't exist yet", async () => {
    await rm(dir, { recursive: true, force: true });
    mod.saveConfig(sample);
    const s = await stat(dir);
    expect(s.isDirectory()).toBe(true);
  });

  it("writes the file with mode 0600 (owner read/write only)", async () => {
    mod.saveConfig(sample);
    const s = await stat(join(dir, "config.json"));
    // Mask to the permission bits; platform/umask can affect higher bits.
    expect(s.mode & 0o777).toBe(0o600);
  });

  it("overwrites a previously saved config", () => {
    mod.saveConfig(sample);
    mod.saveConfig({ ...sample, accessToken: "rotated-token" });
    expect(mod.loadConfig()?.accessToken).toBe("rotated-token");
  });
});

describe("clearConfig", () => {
  it("removes an existing config file", () => {
    mod.saveConfig(sample);
    mod.clearConfig();
    expect(mod.loadConfig()).toBeNull();
  });

  it("does not throw when no config file exists", () => {
    expect(() => mod.clearConfig()).not.toThrow();
  });
});

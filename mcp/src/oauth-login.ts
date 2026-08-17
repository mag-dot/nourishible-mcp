import crypto from "node:crypto";
import http from "node:http";
import open from "open";
import { clearConfig, loadConfig, resolveApiBaseUrl, saveConfig } from "./config.js";

const CLIENT_ID = process.env.NOURISHIBLE_OAUTH_CLIENT_ID ?? "claude-mcp";
const API_BASE_URL = resolveApiBaseUrl();
const CALLBACK_PORT = Number(process.env.NOURISHIBLE_MCP_CALLBACK_PORT ?? 6274);
const SCOPE = "recipes:read recipes:write";

function base64UrlRandom(bytes: number): string {
  return crypto.randomBytes(bytes).toString("base64url");
}

function sha256Base64Url(input: string): string {
  return crypto.createHash("sha256").update(input).digest("base64url");
}

/**
 * CLI-driven Authorization Code + PKCE login, the standard "loopback
 * redirect" pattern for CLI/desktop OAuth clients (same shape gh/gcloud use):
 * spin up a local HTTP server, open the system browser to the backend's
 * /oauth/authorize, catch the redirect on localhost, exchange the code for a
 * token server-to-server, store it, done.
 *
 * Requires the user to already be signed in to nourishible *in that
 * browser* — this flow has no login form of its own, it delegates to the
 * website's session.
 */
export async function login(): Promise<void> {
  const verifier = base64UrlRandom(32);
  const challenge = sha256Base64Url(verifier);
  const state = base64UrlRandom(16);
  const redirectUri = `http://localhost:${CALLBACK_PORT}/callback`;

  const authorizeUrl = new URL("/oauth/authorize", API_BASE_URL);
  authorizeUrl.searchParams.set("client_id", CLIENT_ID);
  authorizeUrl.searchParams.set("redirect_uri", redirectUri);
  authorizeUrl.searchParams.set("response_type", "code");
  authorizeUrl.searchParams.set("code_challenge", challenge);
  authorizeUrl.searchParams.set("code_challenge_method", "S256");
  authorizeUrl.searchParams.set("scope", SCOPE);
  authorizeUrl.searchParams.set("state", state);

  const code = await new Promise<string>((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url ?? "/", `http://localhost:${CALLBACK_PORT}`);
      if (url.pathname !== "/callback") {
        res.writeHead(404).end();
        return;
      }

      const error = url.searchParams.get("error");
      const returnedState = url.searchParams.get("state");
      const returnedCode = url.searchParams.get("code");

      res.writeHead(200, { "Content-Type": "text/html" });
      if (error) {
        res.end(`<h2>Authorization failed: ${error}</h2>You can close this tab.`);
        server.close();
        reject(new Error(`oauth_error: ${error}`));
        return;
      }
      if (returnedState !== state || !returnedCode) {
        res.end("<h2>Authorization failed: state mismatch or missing code.</h2>");
        server.close();
        reject(new Error("state_mismatch"));
        return;
      }

      res.end("<h2>nourishible connected ✅</h2>You can close this tab and return to Claude.");
      server.close();
      resolve(returnedCode);
    });

    server.listen(CALLBACK_PORT, () => {
      console.error(`Opening browser for nourishible login (waiting on http://localhost:${CALLBACK_PORT}/callback)...`);
      console.error(`If a browser doesn't open, visit:\n${authorizeUrl.toString()}`);
      open(authorizeUrl.toString()).catch(() => {
        // headless environment — the printed URL above is the fallback
      });
    });

    server.on("error", reject);
  });

  const tokenRes = await fetch(new URL("/oauth/token", API_BASE_URL), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      client_id: CLIENT_ID,
      code_verifier: verifier,
    }),
  });

  if (!tokenRes.ok) {
    throw new Error(`Token exchange failed: ${tokenRes.status} ${await tokenRes.text()}`);
  }

  const token = (await tokenRes.json()) as { access_token: string; scope: string };
  saveConfig({
    accessToken: token.access_token,
    scope: token.scope,
    obtainedAt: new Date().toISOString(),
    apiBaseUrl: API_BASE_URL,
  });

  console.error(`Logged in. Token stored — the nourishible MCP server is ready to use.`);
}

/**
 * Revokes the stored token server-side (DELETE /oauth/token — see
 * backend/src/auth/oauth.ts) before clearing local config. Doing only the
 * local clear (the previous behavior) left the token valid on the backend
 * for its full 90-day life even after "logout" — a leaked or copied token
 * would keep working regardless of what the user thought they'd done.
 *
 * Best-effort on the revoke call: a network error or an already-invalid
 * token shouldn't block clearing local state, since "am I still logged in
 * on this machine" is the part fully within the user's control. Either way
 * we tell the user what actually happened rather than reporting success
 * unconditionally.
 */
export async function logout(): Promise<void> {
  const config = loadConfig();
  if (!config) {
    console.error("Already logged out (no stored credentials).");
    return;
  }

  try {
    const res = await fetch(new URL("/oauth/token", config.apiBaseUrl), {
      method: "DELETE",
      headers: { Authorization: `Bearer ${config.accessToken}` },
    });
    if (res.ok || res.status === 401) {
      // 401 here means the token was already invalid/expired/revoked —
      // still counts as "successfully not-valid", not a failure to report.
      console.error("Token revoked on the server.");
    } else {
      console.error(
        `Warning: server did not confirm revocation (HTTP ${res.status}) — clearing local ` +
          `credentials anyway, but the token may still be valid until it expires.`
      );
    }
  } catch (err) {
    console.error(
      `Warning: couldn't reach the server to revoke the token (${
        err instanceof Error ? err.message : String(err)
      }) — clearing local credentials anyway, but the token may still be valid until it expires.`
    );
  }

  clearConfig();
}

---
name: recipe-extract
version: "0.1.0"
description: Turn a recipe video (Instagram Reel, YouTube Short/video) into a structured, editable recipe — title, tagged ingredients, numbered steps, servings, source credit — with per-field confidence and a list of what a human reviewer should double-check. Descended from the /watch skill; this is the Claude Code reference implementation nourishible2's backend extraction service (docs/PRODUCT-STRATEGY.md §4.2) is being built from.
argument-hint: "<video-url> [--out DIR]"
allowed-tools: Bash, Read, Write, AskUserQuestion
author: nourishible2
license: MIT
user-invocable: true
---

# /recipe-extract

You don't have a recipe-structuring input; this skill gives you one. It reuses `/watch`'s
script (download, frame-sample, transcribe) to get you the raw evidence — frames +
transcript — and then **you** do the recipe-specific work by hand: reading on-screen
ingredient/step text off the frames (no separate OCR API — you can already read images),
cross-referencing the caption/transcript, and writing a structured recipe JSON that
matches nourishible2's schema (`docs/PRODUCT-STRATEGY.md` §4.5).

This is the skill-form reference implementation the production pipeline is descended
from (see `docs/PRODUCT-STRATEGY.md` §4.2 and `backend/src/extraction/README.md`) — treat
changes here as informing that spec, not drifting from it. If you change the extraction
approach in a way that would change the backend pipeline's steps, note it in
`backend/src/extraction/README.md` too.

## Dependency: requires `/watch`'s scripts as a sibling skill

This skill does not re-implement download/frame-extraction/transcription — it shells out
to `skills/watch/scripts/watch.py` for that (same repo, sibling directory). It does **not**
work standalone outside this repo layout.

## Resolve `SKILL_DIR` and `WATCH_SCRIPT` (do this before any command)

Set `SKILL_DIR` to the absolute path of the directory containing **this** SKILL.md you
just Read. `/watch`'s scripts live at a fixed relative path from there in this repo:

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
WATCH_SCRIPT="$(cd "$SKILL_DIR/../watch/scripts" && pwd)/watch.py"
if [ ! -f "$WATCH_SCRIPT" ]; then
  echo "ERROR: could not find $WATCH_SCRIPT — is skills/watch/ present as a sibling of skills/recipe-extract/?" >&2
  exit 1
fi
```

`/watch`'s own setup preflight (`scripts/setup.py`) still applies — run it once per
session the same way `/watch`'s SKILL.md describes (Step 0 there): it installs
`ffmpeg`/`yt-dlp` and prompts for a Whisper key if missing. Re-read that section if you
haven't run `/watch` yet this session; don't duplicate its logic here.

## When to use

- User pastes an Instagram Reel or YouTube Short/video link and asks to save/extract it
  as a recipe, or types `/recipe-extract <url>`.
- User asks "what's the recipe in this video" for something that is clearly a
  cooking/recipe video.

Not for: general video Q&A (`/watch` handles that), blog/website recipe scraping (out of
scope — see `docs/PRODUCT-STRATEGY.md` §3.2 non-goals), TikTok (deferred, §3.5).

## Step 0.5 — dedup check (do this before spending any download/frame budget)

Before calling `/watch`'s script, check whether this exact video has already been saved
for the target user. **Normalize both the incoming URL and every already-saved
`sourceUrl` before comparing** — a raw string/exact match misses real duplicates:
YouTube URLs routinely carry a tracking `&pp=...`/`&si=...`/`&t=...` param that has
nothing to do with video identity. Extract just the video id (the `v=` param, or the path
segment after `youtu.be/` / `shorts/`) from both sides and compare on that.

**How to check** depends on which persistence path Step 6.5 below ends up using (check
that section once to know which you're in — it's the same choice both times):

- **Nourishible MCP tools available** (the common case once you're connected — see Step
  6.5): call `list_recipes` (no query needed, or narrow with the creator handle/title if
  the library is large) and scan the returned `sourceUrl` values yourself for a matching
  normalized video id. This is a normal in-context text comparison, not a database query
  — you're just reading a JSON list you already have.
- **Direct DB access** (nourishible2 team members working inside this repo, with
  `DATABASE_URL` available): `SELECT id, title, source_url FROM recipes WHERE user_id =
  $1 AND source_url LIKE '%' || $2 || '%'` with `$2` the bare video id, then confirm the
  match in code rather than trusting the LIKE alone. Faster than the API round-trip when
  it's available, but it's a convenience for this repo's own dev/QA use, not something an
  external skill user has.

Either way, if a recipe for that video id already exists for that user:

- Tell the user it's already saved (title + link to it in the app), and ask whether they
  want to re-extract anyway (e.g. the video changed, or the first extraction was poor) —
  don't silently skip, and don't silently re-run and create a duplicate.
- If they confirm a re-extract, update the existing record (`update_recipe` / `PUT
  /recipes/:id`) instead of creating a new one.

This is a cheap check — always pay it before the expensive download/frame/LLM-reasoning
work below.

## Step 0.6 — is this actually a recipe? (reject non-food content early)

Skim the video title, description, and (if quick to get) the first bit of transcript
*before* doing the full frame-extraction pass. Reject and stop, telling the user plainly
why, if:

- The content isn't food/cooking at all (vlogs, hauls, unrelated tutorials, music videos
  that happen to be tagged with a food emoji, etc.).
- It's food-adjacent but not a recipe someone could cook from (a restaurant review, a
  mukbang/eating video with no preparation shown, a "what I eat in a day" montage with no
  method) — these have no ingredients/steps to extract.
- It's an ad/sponsored placement with no actual recipe content, just a product pitch.

A genuine recipe video needs at least one of: a stated or shown ingredient list, or a
sequence of preparation steps (chopping, mixing, cooking, assembling) that a viewer could
follow. If you're not sure after the title/description/opening transcript, it's fine to do
Step 1 and decide from the fuller evidence — but don't structure a fake recipe out of a
video that's clearly not one just because a URL was given to you.

## Step 1 — fetch frames + transcript

Call `/watch`'s script directly, biased for recipe content:

```bash
python3 "$WATCH_SCRIPT" "<video-url>" --detail balanced --resolution 1024 --out-dir "${OUT_DIR:-}"
```

Notes on the flags, and why they differ from `/watch`'s own defaults:

- `--resolution 1024` (not the `/watch` default of 512) — recipe frames frequently carry
  small on-screen text (ingredient callouts, timers, quantity overlays) that needs to be
  legible, not just recognizable. This roughly quadruples image tokens per frame; accept
  that cost here, it's the point of this skill.
- `--detail balanced` is the right starting point for most recipe Reels/Shorts (under
  ~90s, which covers the large majority of recipe content). For a longer-format YouTube
  recipe video, consider `--detail token-burner` or focusing with `--start`/`--end` around
  the actual cooking steps if there's a long cold-open/intro to skip — see `/watch`'s
  "Focusing on a section" guidance.
- If the URL is `instagram.com` and the run fails to produce video/captions, follow
  `/watch`'s Instagram cookie-auth guidance (`--cookies-from-browser` /
  `--cookies`) before giving up — this is the expected failure mode Instagram produces
  for anonymous requests, not a bug.
- Pass `--out DIR` through as `--out-dir` if the user (or your caller) specified one;
  otherwise let it use the default tmp dir.

**Transcript-cue pass (recommended for recipes specifically):** after the first run, scan
the transcript for the moments a cook typically narrates quantities/technique ("add two
tablespoons of...", "let that go for five minutes", "fold in the..."). If the initial
scene-aware frame selection landed sparsely around those moments, re-run once with
`--timestamps` pinned to them (per `/watch`'s "Transcript-cue frames" section), pointed at
the already-downloaded local file so it doesn't re-download. This matters more for
recipes than general video Q&A because a quantity is often only correct at one specific
frame (the measuring cup on screen), not "somewhere in this scene."

## Step 2 — read everything

`Read` every frame path the script printed, in one batch (parallel tool calls), same as
`/watch`. You now have three evidence streams to reconcile, not two:

1. **Frames** — what's visually on screen, including any on-screen text overlays
   (ingredient lists, quantities, step callouts, timers). Read the overlay text directly
   off the image — don't guess if it's legible.
2. **Transcript** — what's spoken, with timestamps (`captions` = native, `whisper (...)` =
   transcribed — the report header says which).
3. **Caption/description text** — if the source is Instagram, the post caption itself
   (printed in the report) very often contains the full ingredient list as plain text,
   sometimes *more* complete than what's shown on screen or said aloud. Treat it as a
   first-class source, not an afterthought.

## Step 3 — structure the recipe

Produce a recipe JSON matching this schema exactly (mirrors `docs/PRODUCT-STRATEGY.md` §4.5 —
if that schema changes, update this skill to match, and vice versa):

```json
{
  "title": "string",
  "sourceUrl": "string (the URL you were given)",
  "sourcePlatform": "instagram | youtube",
  "creatorHandle": "string",
  "thumbnailFramePath": "path to the single best-representative frame from Step 1 (not a new download — pick from what you already extracted)",
  "servings": "integer, best estimate if unstated (say so in confidence notes)",
  "totalTimeMinutes": "integer or null",
  "ingredients": [
    {
      "rawText": "the original line as seen/heard, verbatim",
      "quantity": "number or null (null for 'to taste')",
      "unit": "string or null, normalized (tbsp, tsp, g, cup, ml, oz, clove, pinch, ...)",
      "name": "string",
      "optional": "boolean",
      "category": "produce | protein | dairy | pantry | other, or null"
    }
  ],
  "steps": [
    { "text": "string, one clear instruction per step", "timestampSeconds": "number or null — the source video moment this step corresponds to, if you can pin it" }
  ],
  "tags": ["cuisine/meal-type/dietary tags you can confidently infer — don't force it"],
  "notes": "string or null — anything worth flagging that doesn't fit elsewhere",
  "confidence": {
    "<field path, e.g. 'ingredients[2].quantity'>": "high | medium | low"
  }
}
```

Structuring rules:

- **Reconcile, don't just concatenate.** When caption text, on-screen text, and spoken
  audio disagree on a quantity or ingredient, prefer on-screen text > caption text >
  spoken audio, in that order (a displayed number is usually the most precise; spoken
  numbers are the easiest to mishear/mistranscribe) — but only when they actually
  disagree. Note the conflict in `notes` or a low confidence flag either way.
- **One ingredient per line.** Split combined lines ("salt and pepper to taste" → two
  ingredient entries) so each is independently taggable/scalable, matching the sub-schema.
- **Normalize units** to a small controlled vocabulary (tbsp, tsp, cup, g, kg, ml, l, oz,
  lb, clove, pinch, can, bunch) rather than preserving every raw spelling — but keep the
  original in `rawText` regardless.
- **Steps should be actions, not narration.** Compress "so what I'm gonna do now is just
  go ahead and add in about a cup of..." into "Add 1 cup of...". Keep the count of steps
  close to what a person would actually check off while cooking (typically 4-10 for a
  Reel-length recipe) — don't over-split.
- **Servings/time**: if genuinely unstated anywhere (caption, audio, on-screen), give your
  best estimate from the ingredient quantities/format shown and mark it `low` confidence
  rather than leaving it null — the app needs a starting number to scale from.

## Step 4 — confidence scoring

For every field you're not fully certain of, add an entry to `confidence`. Use this as
the actual criteria, not a vibe:

- **high** — stated identically (or compatibly) in at least two of {on-screen text,
  caption, audio}, or stated unambiguously in one source with no conflicting signal from
  the others.
- **medium** — stated clearly in exactly one source, with the others silent (not
  conflicting) on that field.
- **low** — sources disagree, the source was ambiguous/partially obscured, or you're
  estimating/inferring (e.g. servings backed out from ingredient quantities, a step
  timestamp you're not sure aligns).

Don't add high-confidence fields to the map at all — only flag what a reviewer should
actually look at. A recipe where nothing needs a second look should have a small or empty
`confidence` object, not one entry per field.

## Step 5 — refinement suggestions

Separately from the JSON (this is for the human, not part of the saved record), write a
short **"Worth double-checking"** list: 2-6 bullets, each naming a specific field and why
— this is the same signal `confidence` carries, but phrased as something a reviewer can
act on in a few seconds. Examples of the right level of specificity:

- "Soy sauce quantity (2 tbsp) — only heard on audio, not shown or captioned; the pour
  looked closer to 3 tbsp on screen."
- "Step 4 timing (5 minutes) — caption says 'simmer until reduced', audio says
  '5 minutes', used the audio number but reduction time varies more than that suggests."
- "Servings (4) — never stated anywhere, backed out from a family-size portion shown at
  the end; treat as a rough estimate."

Skip this list entirely (say so plainly) if the extraction was clean and nothing scored
`low`/ambiguous — don't manufacture concerns to fill space.

## Step 5.5 — pick the best 3 frames for preview thumbnails

The current schema (`recipeInputSchema` / `docs/PRODUCT-STRATEGY.md` §4.5) only carries a
single `thumbnailUrl`, but still do this ranking — it's what feeds that one field today
and what a future multi-image gallery would consume without redoing the work. From the
frames you already read in Step 2, pick the 3 strongest candidates using these criteria,
in order:

1. **Finished-dish shot** — the plated/finished result, well-lit, food filling most of the
   frame, no hands/utensils obscuring it. This is always candidate #1 if one exists. A minor
   caption or watermark in a corner/margin doesn't disqualify a frame — a full, unobstructed
   view of the dish beats losing the shot entirely over small on-screen text.
2. **A striking mid-process shot** — a visually distinct cooking moment (a sizzling pan, a
   sauce being poured, a key ingredient close-up) that would read well as a card image even
   out of context.
3. **A second angle of the finished dish, or the best remaining candidate** — prefer
   variety (don't pick three near-duplicate frames of the same moment).

Reject frames that are: blurry/motion-blurred, mostly a person's face/torso with no food
visible, dominated by a hand/utensil obscuring the food, transition frames (mid-cut,
part-black), or where text/graphics cover a substantial part of the dish itself (not just
empty background — a short caption along the bottom edge is fine, a title card plastered
across the food is not).

Record your #1 pick's frame path — that's the one to persist as the recipe's thumbnail in
Step 6.5 below (via `set_recipe_thumbnail` / `POST /recipes/:id/thumbnail`, never by
hotlinking a frame off local disk — the recipe row only ever stores a cached URL). Note
the #2 and #3 picks in your summary to the user even though there's nowhere in the schema
to persist them yet — flag to the user that multi-image storage would need a schema/API
change if they want it saved, don't silently build it.

**Don't skip this and fall back to a platform-provided thumbnail** (YouTube's
`i.ytimg.com/vi/<id>/hqdefault.jpg`, an Instagram CDN URL, etc.) just because it's easier
to grab from video metadata — that was tried once and had two problems: it isn't a frame
*you* picked for quality (no control over hands/face/text in it), and platform CDN links
can be signed/expiring (Instagram's are; YouTube's happen to be stable but that's not
guaranteed). Always upload an actual picked frame — the mechanics of *how* depend on
which persistence path Step 6.5 uses (`set_recipe_thumbnail`, or a direct
`POST /recipes/:id/thumbnail` call, both covered there) — even when that feels like the
slower path.

## Step 6 — write the output

Save the recipe JSON to a file in the working directory `/watch` reported (or `--out DIR`
if the caller specified one):

```bash
# after composing the JSON content, e.g.:
# Write "$OUT_DIR/recipe.json" <the JSON>
```

Then show the user: the recipe as a readable summary (title, ingredients, steps,
servings/time), the source credit (creator handle + link — **always** include this,
per `docs/PRODUCT-STRATEGY.md` §3.1 goal 4, never presented as this skill's own content), and
the "Worth double-checking" list from Step 5.

## Step 6.5 — persist to nourishible

Don't stop at the JSON file — the point of this skill is a saved recipe the user can open
in the app, under *their own* nourishible account. This is the one step where "inside the
company repo" and "anyone running this skill against their own account" genuinely
diverge — read the right subsection below.

### The normal path: save via the nourishible MCP tools

If you can see `save_recipe`, `update_recipe`, `set_recipe_thumbnail`, `list_recipes`,
and `get_recipe` as callable tools in this session, use them — this is true whenever the
user has connected the `nourishible-mcp` server to their agent (see
[`mcp/README.md`](../../mcp/README.md), or the friendlier walkthrough at
`nourishible.com/mcp` once that's live). These tools already talk to the real backend
over the OAuth2 + PKCE flow scoped to that one user's account — there is no separate
auth step for you to implement here, and no server-side code to write.

1. **Re-run the Step 0.5 dedup check** immediately before saving, not just at the start —
   call `list_recipes` again right before you save, to protect against a race with
   anything else that wrote to this account since you first checked.
2. **New recipe:** call `save_recipe` with the exact JSON from Step 3.
   **Re-extract of an existing one** (Step 0.5 found a match and the user confirmed):
   call `update_recipe` with that recipe's `id` and only the fields that changed —
   omitted fields are left untouched, so don't resend the whole object out of habit.
3. **Thumbnail:** call `set_recipe_thumbnail` with the saved/updated recipe's `id` and
   the local file path of your Step 5.5 #1 pick. Do this every time there's a frame to
   give it — a recipe saved without this call shows with no thumbnail in the library.
4. Read back the tool's response for the real `id`/`slug` nourishible assigned, and use
   that (not anything you invented) in your Step 6 summary to the user.

**If those tools aren't available**, stop and tell the user plainly that this skill needs
a connected nourishible account to save anything — point them at `nourishible.com/mcp`
(or `mcp/README.md` if they're comfortable running `npm install && npm run login`
themselves) to connect one, then retry. Don't try to improvise the OAuth flow yourself
from raw HTTP calls in this skill — that flow already has one correct, tested
implementation (`mcp/src/oauth-login.ts`); a second hand-rolled copy living here would
just be a second place for it to silently drift out of sync and break.

### Internal-only: direct DB access (nourishible2 team working in this repo)

Skip this whole subsection unless you're a nourishible2 team member with `DATABASE_URL`
access to an actual deployment, working *inside this repo* — it's a dev/QA convenience
for people building the product, not something an external skill user has or should be
told to set up. If both this and the MCP-tools path above are available, prefer the
tools path — it's what an external user's identical run would actually do, so testing
through it catches real bugs the direct-DB shortcut can't.

**Which database(s)?** Ask if it's not obvious from context. If the user says "save it" /
"add it" with no qualifier and this session has an established pattern of saving to both
(check recent conversation/memory), do both; otherwise default to local dev only and
mention prod is available on request.

**Local dev** — `backend/.env`'s `DATABASE_URL` already points at it:

```bash
cd backend && set -a && source .env && set +a && npx tsx <your-seed-script>.ts
```

**Production** — the prod Postgres has no public proxy, only an internal Railway
hostname, so tunnel in first (see the `prod-db-access` memory if this session has one):

```bash
railway connect Postgres --tunnel-only --port 15432   # prints a postgresql:// URL on 127.0.0.1
# in another call, with that URL:
DATABASE_URL="postgresql://postgres:<password>@127.0.0.1:15432/railway" npx tsx <your-seed-script>.ts
pkill -f "railway connect"                             # close the tunnel when done — don't leave it open
```

If port 15432 is already bound from a previous run, `lsof -i :15432 -t | xargs -r kill -9`
before retrying.

**The seed script itself** should, every time (don't skip steps to save typing):
1. Import `recipeInputSchema` from `backend/src/recipes/schema.ts` and `query`/`pool` from
   `backend/src/db.ts` — reuse the backend's own validation, don't hand-roll a parallel one.
2. Look up the target user by email (`SELECT id FROM users WHERE email = $1`); create the
   user only if this is a deliberate first save for a new person, not silently.
3. Re-run the dedup check (Step 0.5's normalized-video-id comparison) against that
   specific database before inserting — local and prod are separate databases with
   separate history, a dedup pass in one says nothing about the other.
4. Insert via the same column set `POST /recipes` uses (see `backend/src/recipes/routes.ts`
   for the exact statement) so the row is indistinguishable from one saved through the app.
5. For a thumbnail, still go through the real `POST /recipes/:id/thumbnail` endpoint
   rather than writing to storage directly — mint a throwaway session row the same way,
   call the endpoint, then delete the session row immediately after:
   ```bash
   TOKEN=$(node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))")
   psql "$DSN" -c "insert into sessions (token, user_id, expires_at) values ('$TOKEN', '$USER_ID', now() + interval '1 day');"
   curl -s -X POST "$API_BASE/recipes/$RECIPE_ID/thumbnail" \
     -H "Content-Type: image/jpeg" -H "Cookie: nourishible_session=$TOKEN" \
     --data-binary "@/path/to/your/picked/frame.jpg"
   psql "$DSN" -c "delete from sessions where token='$TOKEN';"
   ```
6. Print the inserted `recipe_...` id so you can tell the user exactly what was saved where.
7. Delete the throwaway script afterward — it's scratch, not part of the repo.

## Step 7 — clean up

Same as `/watch` Step 5: if there's no likely follow-up on this specific video, `rm -rf`
the working directory once the JSON has been shown/saved wherever the user wants it kept.
If the user might ask to re-extract or adjust, leave it.

## Failure modes and handling

- **`/watch` script fails** (download/auth/transcript issues) — follow `/watch`'s own
  failure-mode table (its SKILL.md "Failure modes and handling" section); this skill adds
  no new failure surface at that layer.
- **No usable ingredient list found anywhere** (frames, caption, audio) — don't fabricate
  one. Tell the user the video doesn't appear to state ingredients/quantities clearly
  enough to extract, and offer to proceed with what's inferable (e.g. dish name +
  technique only) if they still want a draft.
- **Video isn't actually a recipe** — say so plainly rather than forcing a recipe-shaped
  output onto unrelated content.
- **Multiple recipes in one video** (e.g. "3 ways to use leftover rice") — ask the user
  (via `AskUserQuestion`) which one they want, or whether they want all of them as
  separate recipe JSONs, rather than merging them into one incoherent recipe.

## What this skill deliberately does NOT do (vs. the production pipeline)

`docs/PRODUCT-STRATEGY.md` §4.2 describes a 9-step server-side pipeline with a dedicated OCR
pass and a worker-account pool for Instagram auth. This skill simplifies two of those for
the interactive/Claude Code context, intentionally:

- **No separate OCR step** — you (Claude) read on-screen text directly off the frames in
  Step 2/3. The production service needs a dedicated OCR pass because it's unattended and
  cheaper at scale than a full multimodal call per frame; that's a backend cost
  optimization, not a capability this skill is missing.
- **No worker-account pool** — this skill relies on `/watch`'s browser-cookie auth
  (`--cookies-from-browser`) for Instagram, which needs an interactive user with a logged-in
  browser. That doesn't translate to an unattended backend service, which is exactly why
  §4.3 calls out the worker-account pool / browser-relay question as something Phase 0
  needs to resolve separately — this skill doesn't resolve it, it just isn't blocked by it.

## Security & Permissions

**What this skill does**, on top of everything `/watch` already does (see that skill's
own Security & Permissions section for the download/transcription layer):
- Reads frame images and the transcript/caption text that `/watch` already wrote to its
  working directory
- Writes one additional file, `recipe.json`, to that same working directory
- Calls the `save_recipe`/`update_recipe`/`set_recipe_thumbnail`/`list_recipes`/
  `get_recipe` nourishible MCP tools (Step 6.5) when the user has connected one — these
  talk to the real nourishible backend, scoped to that one user's account via an OAuth
  bearer token the user granted when they connected it. This skill never sees or handles
  the user's password; it only ever calls tools already authorized for that account.
- Persists the structured recipe (and, if picked, a thumbnail image) to the user's real
  nourishible library via that connection — that's the point of Step 6.5, not a side
  effect to be surprised by.

**What this skill does NOT do:**
- Does not call any additional third-party API (no separate OCR service, no separate LLM
  API call — the structuring happens in your own reasoning, same as any other skill
  output)
- Does not implement its own OAuth/network client for the save step — it only ever calls
  the already-connected MCP tools; if none are connected, it stops and tells the user to
  connect one rather than inventing a parallel auth path (see Step 6.5)
- Does not persist anything outside the working directory *and* the user's own
  nourishible account via the path above
- Does not modify `docs/PRODUCT-STRATEGY.md` or the backend service on its own — if extraction
  experience here suggests the spec should change, say so to the user rather than editing
  those files unprompted

**Bundled files:** this skill has no scripts of its own — it is a `SKILL.md` only, reusing
`skills/watch/scripts/watch.py` from the sibling `/watch` skill. Review that skill's
scripts (linked from its own SKILL.md) before first use. The nourishible MCP tools it
calls in Step 6.5 (when connected) come from the separate `mcp/` package — review that
package's own Security & Permissions section (`mcp/README.md`) too.

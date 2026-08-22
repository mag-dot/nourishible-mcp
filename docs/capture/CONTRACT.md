# Acquisition contract

**Status:** binding for this engine and for every consumer of it, including nourishible.com.
**Last verified against Meta's terms:** 14 Aug 2026.

This is the one constraint that cannot be traded away for convenience. It is written down
because a consumer inheriting this engine inherits the constraint too, and finding out later
is expensive.

---

## The rule

> **Content enters this system only because a human caused it to play or be shared.
> Nothing in this system fetches Instagram content programmatically.**

That is the whole contract. Everything below explains why, and what it permits.

---

## What Meta's terms actually say

Instagram Terms of Use, prohibited conduct:

> "You may not access or collect data from our Products using automated means (without our
> prior permission) or attempt to access data you do not have permission to access."

Two readings matter, and the second is the one people get wrong:

1. **It is not limited to downloading.** "Access… using automated means" covers programmatic
   *navigation and interaction* with a logged-in session, not only bulk data extraction.
   Driving a browser to open post URLs and press play is automated access even if nothing is
   saved to disk.

2. **It applies to your own account and your own saved posts.** There is no
   "but it's my data" exemption. Meta enforces this actively — there is a dedicated help page
   for accounts restricted for scraping.

**Consequence:** the risk is not a lawsuit. It is losing the account, which for a personal
recipe tool is a total loss of the corpus.

---

## Permitted

| Action | Why it is fine |
|---|---|
| Parsing your official data export | Meta built the export for this |
| Recording your own screen while you play a reel | Zero requests to Meta; the traffic is you using the app |
| `open <url>` in your normal browser | Indistinguishable from clicking a bookmark |
| Local processing of a file you already have | Never touches Meta |
| Pasting a caption or a DM you received | You are the transport |
| An agent screenshotting a tab **you** opened and played | Same act as recording your screen; the agent is the recorder, not the requester |
| An agent seeking within a reel you already watched through | Reads the buffer your playback loaded; no new request |

## Not permitted

| Action | Why not |
|---|---|
| `yt-dlp`, scrapers, unofficial APIs | Automated fetch — the prohibited category |
| Headless/automated browser on instagram.com | Automated access with your session |
| Scripting the play button on a page a script opened | Same as above; the click is the automation |
| Batch-walking a list of post URLs unattended | The pattern enforcement is designed to catch |
| Hotlinking Instagram CDN URLs in a rendered page | Re-fetches from Meta on every page view |
| An agent calling `navigate` on an instagram.com URL | The agent initiated the request — automated access, however it is framed |
| An agent clicking play, or seeking a reel nobody watched | Turns buffering into a fetch the agent caused |
| An agent working through several posts in one session | Batch-walking; the capture mechanism does not change the pattern |

**YouTube and recipe websites are different** and are not covered by this contract. YouTube has
an official API and published captions; recipe sites often publish `schema.org/Recipe` JSON-LD
and can be fetched normally, respecting `robots.txt`. Those adapters may run unattended.

---

## The line, precisely

The distinguishing question is **who initiated the request to Meta's servers.**

```
You press play, we record the screen        →  0 requests from us.  PERMITTED
Queue opens a URL, you press play           →  0 requests from us.  PERMITTED
Script opens a URL and presses play         →  automated session.   NOT PERMITTED
Script logs in and walks a list             →  automated session.   NOT PERMITTED
```

```
You open + play, an agent screenshots     →  0 requests from it.  PERMITTED
Agent navigates to the post, you play      →  agent initiated.     NOT PERMITTED
Agent seeks a reel you never watched       →  agent caused fetch.  NOT PERMITTED
```

`scripts/serve.mjs` sits on the permitted side by construction: it opens a URL in your normal
browser and then **waits for playback it did not cause**. If you never press play, nothing is
captured. That is not a limitation to engineer around — it is the mechanism that keeps this
compliant.

---

## Autoplay, and why it is not a loophole

Chrome blocks unmuted autoplay until a site earns it. Three routes exist; only one is
acceptable here.

| Route | Verdict |
|---|---|
| **Media Engagement Index** — Chrome learns you watch media on a site and grants autoplay | **Fine.** Earned by your ordinary use, in your ordinary profile. Nothing is automated. |
| **A real click** you make | **Fine.** It is a user gesture because a user made it. |
| `--autoplay-policy=no-user-gesture-required` | **No.** Requires a separate Chrome profile and an automated login — exactly the prohibited pattern. |

Measured on this machine (14 Aug 2026): `instagram.com` has 54 visits, 9 media playbacks,
`hasHighScore: false`. **The MEI threshold is not yet met**, so unmuted autoplay is not
currently granted. It accrues with normal use — each unmuted playback over ~7 seconds counts.

Until then, one tap per reel. That is the honest cost.

---

## Agent-controlled browsers

An agent (Claude in Chrome, or any MCP browser tool) driving the browser does **not** get
a different contract. It sits on the permitted side under exactly one arrangement:

> The human navigates to the post and plays it. The agent then reads and screenshots the
> page they are already looking at.

That is the local screen-capture arrangement with a different recorder, so it inherits the
same verdict. What flips it to the prohibited side is the agent supplying the *initiation*
— navigating to a URL, pressing play, opening the next post in a list. The capability to
do those things is exactly why this needs writing down: an agent that can navigate will
navigate unless told not to.

Two consequences worth stating plainly, because they look like harmless conveniences:

1. **"Just open the URL for them" is the prohibited pattern**, not a shortcut around a
   clunky UX. The waiting is the mechanism.
2. **Seeking is bounded by what the human played.** Scrubbing a fully-buffered reel they
   watched is reading memory. Seeking a video nobody played can trigger range requests to
   Meta's CDN that the agent caused — so require a full playthrough first.

## What this means for a consumer of the engine

If you build on this engine (nourishible.com or anything else):

1. **Do not add an Instagram fetch path.** Not on your server, not in a worker, not "just for
   testing", and not by handing an agent a browser and letting it navigate. The engine deliberately has no such capability; adding one transfers the account
   risk to whoever's credentials are used.
2. **Instagram jobs are asynchronous by nature.** A submitted Instagram URL enters
   `needs-capture` and stays there until a human plays it. Your UI must be able to show
   "waiting for capture" as a normal state, not an error.
3. **Cover images are local files.** Upload them to your own storage. Do not render Instagram
   CDN URLs.
4. **YouTube and web URLs return synchronously.** Design for both paths.

---

## If this ever needs to change

The only compliant route to automated Instagram access is **prior written permission from
Meta**, which the terms explicitly contemplate ("without our prior permission"). That means a
platform partnership, not a header or a rate limit. Until that exists, this contract holds.

Re-verify the quoted clause before any change to acquisition. Terms move.

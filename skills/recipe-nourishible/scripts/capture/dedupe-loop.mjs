#!/usr/bin/env node
/**
 * Collapses a looping capture down to one clean pass.
 *
 * Instagram reels loop until you stop them. That is a feature for capture —
 * record 2-3x the reel length and a complete pass is guaranteed without any
 * timing precision. The cost is duplicated content, in two forms:
 *
 *   1. OCR text repeats across every frame showing the same overlay, and then
 *      repeats again on each loop.
 *   2. The transcript says everything two or three times.
 *
 * Feeding that to the extractor produces triplicated ingredients, so this runs
 * between capture and extraction.
 *
 * Usage: node scripts/dedupe-loop.mjs <captureDir>
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const dir = process.argv[2];
if (!dir) {
  console.error('usage: node scripts/dedupe-loop.mjs <captureDir>');
  process.exit(1);
}

/**
 * Normalise for comparison, folding the character confusions OCR actually
 * makes on overlay text: l/I -> 1, O -> 0, S -> 5. Without this, "1 cup oats"
 * and "l cup oats" read as different lines and both survive dedup.
 */
const norm = (s) =>
  s
    .toLowerCase()
    .replace(/[il|]/g, '1')
    .replace(/o/g, '0')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

/** Token-overlap similarity. Cheap, and good enough for near-identical lines. */
function similarity(a, b) {
  const A = new Set(norm(a).split(' ').filter(Boolean));
  const B = new Set(norm(b).split(' ').filter(Boolean));
  if (!A.size || !B.size) return 0;
  let shared = 0;
  for (const t of A) if (B.has(t)) shared++;
  return shared / Math.max(A.size, B.size);
}

/**
 * Keeps the first occurrence of each distinct line.
 *
 * Threshold 0.8 rather than exact match because OCR is not deterministic
 * across frames — the same overlay yields "1 cup oats" on one frame and
 * "1 cup oats." or "l cup oats" on the next. Exact-match dedup leaves those in.
 */
/**
 * Desktop chrome that is never reel content.
 *
 * Second line of defence behind CROP. When a capture catches the whole screen,
 * OCR returns hundreds of lines of terminal output, chat, menu bars and clock
 * readings. Beyond drowning the recipe, that sweeps PRIVATE content (messages,
 * contact names, phone numbers) into plain-text files on disk. Dropping it
 * here keeps it out of the extractor and out of anything downstream.
 */
const DESKTOP_NOISE = [
  /^\d{1,2}:\d{2}\s*(am|pm)?/i, // clock readings
  /^\d{1,3}%/, // battery
  /^\[?(in|out)#\d/i, // ffmpeg logs
  /0x[0-9a-f]{6,}/i, // memory addresses
  /MacBook-Pro:|kennethchan\$|bash-\d/i, // shell prompts
  /^(Search|Playlists|Podcasts|Your Library|Unread|Favorites|Groups|All)$/i,
  /^(File|Edit|View|Window|Help|Shell|Terminal)$/i, // menu bars
  /^\+?\d[\d\s()-]{7,}$/, // phone numbers
  /Pull requests|node_modules|package(-lock)?\.json|tsconfig/i,
  /^[»>\-•*~@\[\]/&+.]+$/, // punctuation-only OCR artefacts
  /avfoundation|pixel format|uyvy|yuyv|nv12|rgb0|bgr0/i,
  // Kitchen appliance displays. A Vitamix in shot showed "12 CUPS MAX
  // CAPACITY" and its timer digits, all of which read as quantity lines.
  /\b(max capacity|vitamix|thermomix|nutribullet|kitchenaid|magimix)\b/i,
  /^\s*\d{1,2}\s*(?:cups?|cU|CUE)\s*(?:MA|MAX)?\s*$/i,
  // Our own intake page, which is often open on the same display.
  /Get Contents of URL|Shortcut Input|request body|one link or a whole list/i,
  /clicking a bookmark|press play\. See|pending\s*[•·]\s*\d+\s*total/i,
  /Recording starts|RECORDING \d+s|Switch to the reel/i, // our own script
];

/**
 * Recipe-shaped text: a quantity, a unit, a cooking verb, an age, or a known
 * food word.
 *
 * WHY AN ALLOWLIST. Tested against a real full-screen capture, the blocklist
 * above dropped 100 of 307 lines and still left the user's phone number and
 * WhatsApp messages in the output. A blocklist can only remove what it has
 * been taught to recognise, and personal content is unbounded — there is
 * always another shape it has not seen.
 *
 * Inverting it makes the failure mode safe: an unrecognised line is DROPPED,
 * so the worst case is a missed ingredient (visible, correctable) rather than
 * a private message written to disk (invisible, not correctable). Cropping
 * remains the real fix; this is the backstop for when the crop is imperfect.
 */
const RECIPE_SHAPED = [
  /^\s*[\d½¼¾⅓⅔]/, // starts with a quantity
  /\b(cup|cups|tbsp|tsp|tablespoons?|teaspoons?|g|kg|ml|oz|lb|tin|can|clove|slice|handful|pinch)\b/i,
  /\b(mash|blend|blitz|bake|steam|boil|fry|mix|stir|cut|spread|freeze|cook|roast|grate|whisk|serve|press|combine|simmer|drain)\b/i,
  /\b\d{1,2}\s*(m|mo|months?)\b|\b(six|seven|eight|nine|ten|eleven|twelve)\s+months?\b/i,
  /\b(oats?|banana|avocado|apple|pear|berry|berries|blueberr|raspberr|strawberr|yog(?:h)?urt|cheese|cheddar|milk|butter|egg|flour|bread|pasta|rice|potato|carrot|broccoli|spinach|pea|lentil|bean|chickpea|salmon|fish|chicken|beef|tofu|hummus|tomato|courgette|pumpkin|squash|mango|chia|seed|nut|coconut|oil|parsnip|cauliflower|quinoa|porridge|cereal|iron|protein|fiber|fibre|allerg|puree|weaning|toddler|infant)\b/i,
  /\b(recipe|ingredients?|method|serves?|prep|allergens?)\b/i,
];

function isRecipeShaped(line) {
  return RECIPE_SHAPED.some((re) => re.test(line));
}

function isDesktopNoise(line) {
  const t = line.trim();
  if (t.length < 2) return true;
  // Mostly non-alphanumeric is an OCR artefact, not text.
  const alnum = (t.match(/[a-z0-9]/gi) ?? []).length;
  if (alnum / t.length < 0.4) return true;
  if (DESKTOP_NOISE.some((re) => re.test(t))) return true;
  // Default-deny: anything not recognisably about food is discarded.
  return !isRecipeShaped(t);
}

function dedupeLines(lines, threshold = 0.8) {
  const kept = [];
  let dropped = 0;
  for (const line of lines) {
    const t = line.trim();
    if (!t) continue;
    if (isDesktopNoise(t)) {
      dropped++;
      continue;
    }
    if (!kept.some((k) => similarity(k, t) >= threshold)) kept.push(t);
  }
  return { kept, dropped };
}

/**
 * Finds where a transcript starts repeating itself and truncates there.
 *
 * A looped transcript is roughly P+P+P for reel content P. We look for the
 * first sentence recurring later in the text; that recurrence marks the loop
 * boundary. Requires a few sentences of separation so a genuinely repeated
 * phrase ("cut lengthways, never coins") does not trigger a false cut.
 */
function truncateAtLoop(text) {
  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);

  if (sentences.length < 4) return { text, loopFoundAt: null };

  const first = sentences[0];
  for (let i = 3; i < sentences.length; i++) {
    if (similarity(first, sentences[i]) >= 0.75) {
      return { text: sentences.slice(0, i).join(' '), loopFoundAt: i };
    }
  }
  return { text, loopFoundAt: null };
}

const report = { onscreen: null, transcript: null };

// --- on-screen text ----------------------------------------------------------
const onscreenPath = join(dir, 'onscreen.txt');
if (existsSync(onscreenPath)) {
  const raw = readFileSync(onscreenPath, 'utf8').split('\n');
  const { kept, dropped } = dedupeLines(raw);
  writeFileSync(join(dir, 'onscreen.clean.txt'), kept.join('\n') + '\n');
  report.onscreen = {
    before: raw.filter((l) => l.trim()).length,
    after: kept.length,
    desktopNoiseDropped: dropped,
  };
}

// --- transcript --------------------------------------------------------------
const transcriptPath = join(dir, 'transcript.txt');
if (existsSync(transcriptPath)) {
  const raw = readFileSync(transcriptPath, 'utf8').trim();
  if (raw) {
    const { text, loopFoundAt } = truncateAtLoop(raw);
    writeFileSync(join(dir, 'transcript.clean.txt'), text + '\n');
    report.transcript = {
      beforeChars: raw.length,
      afterChars: text.length,
      loopDetected: loopFoundAt !== null,
    };
  }
}

console.log(JSON.stringify(report, null, 2));

if (report.onscreen) {
  console.log(
    `\non-screen: ${report.onscreen.before} lines -> ${report.onscreen.after} unique`,
  );
}
if (report.transcript) {
  console.log(
    report.transcript.loopDetected
      ? `transcript: loop detected, trimmed ${report.transcript.beforeChars} -> ${report.transcript.afterChars} chars`
      : `transcript: no loop detected (${report.transcript.afterChars} chars)`,
  );
}

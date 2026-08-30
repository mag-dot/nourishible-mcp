# Attribution

This skill is the merged, publishable successor to work that lived in nourishible's own
private repository:

- The YouTube download/frame-extraction/transcription approach (`scripts/*.py`, excluding
  `capture/`) originates from **`/watch`**, MIT-licensed, by
  [bradautomates](https://github.com/bradautomates/claude-video). That skill's own
  license/attribution is carried forward here — see its homepage for the original.
- The recipe-specific structuring, confidence-scoring, and thumbnail-selection approach
  originates from nourishible's own internal `/recipe-extract` skill, the reference
  implementation nourishible's backend extraction pipeline is descended from.
- The Instagram screen-capture pipeline (`scripts/capture/`) originates from `ig-saved`, an
  earlier project by the same team, retired into nourishible's private repository and
  vendored here in turn — window-detection/crop-geometry logic and the OCR/caption-reading
  approach are carried forward as-is; the parts specific to `ig-saved`'s own standalone
  local-tool use case (a prototype UI, a catalog store, a job queue) were not, since this
  skill's own structuring (Step 2/3) and nourishible's library already cover that ground.
  [`docs/capture/CONTRACT.md`](../../../docs/capture/CONTRACT.md) is the acquisition rule this
  pipeline exists to satisfy — read it before changing anything about how content is
  captured.

If you're looking for the general-purpose (non-recipe) video-Q&A skill `/watch` itself
provides, its original, actively maintained version is at
[bradautomates/claude-video](https://github.com/bradautomates/claude-video) — this skill
is recipe-specific and doesn't attempt to replace that broader use case.

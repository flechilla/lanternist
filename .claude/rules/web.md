---
paths:
  - "web/**"
---

# The web app

React 19, TypeScript (strict), react-router 7, Vite. No state library and no UI kit. Prettier owns
the layout; ESLint (type-aware, with the React hooks rules) and `tsc` run in CI. Scripts are in
`web/package.json`.

## Structure

- `api.ts` holds the only `fetch` calls and every response type. Pages and components call `api.*`.
- `hooks.ts` has the shared hooks. Reach for them before writing another:
  - `useAction()` for any button that awaits: `busy`, `error`, `run`.
  - `useOptions()` for `/api/options`, cached per page load.
  - `useJobStreams()` to follow jobs over SSE.
- Turn a rejection into a message with `errorMessage(e)` from `api.ts`, typed `(e: unknown)`.
  Don't write `e.message` inline.
- `pages/` holds one component per route; `components/` holds pieces used by more than one page, or
  big enough to read alone.
- Styles live in `styles.css`: colour tokens on `:root`, redefined under
  `prefers-color-scheme: dark`. Use the tokens (`var(--ink)`, `var(--lamp)`); never a raw colour in
  a component. Reuse the existing classes (`panel`, `stack`, `field`, `chip`, `quiet`, `small`,
  `danger`, `primary`) before adding a class.

## React

- Derive values during render instead of copying them into state with an effect (see the narrator in
  `NewStory.tsx`). Effects are for subscriptions and fetching. Set state in the `.then` of a fetch,
  not synchronously in the effect body.
- Read the latest callback inside an effect with `useEffectEvent`, not a ref assigned during render.
- Every promise is awaited, handled with a rejection handler, or marked `void` on purpose.
- Keep async click handlers going through `useAction().run`, so busy and error state stay consistent.

## Copy and accessibility

- UI text is plain sentences that say what happens and what to do: "The narrator voice isn't in your
  voices. Pick another on the Script step or add it on Voices." No exclamation marks and no jargon
  (say "picture", not "keyframe").
- Keep the accessibility the code already has: `aria-label` on icon buttons, `aria-pressed` on
  toggles, `role="status"` or `aria-live` on progress, and labels bound to inputs.
- Don't hard-code a backend fact (languages, stages, words per minute, provider env vars). Read it
  from the API; see `.claude/rules/api-contract.md`.

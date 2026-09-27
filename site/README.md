# The site

The public site at lanternist.dev has two pages, and one invitation list behind both.

- `/` is a magic-lantern show in paper cut-outs. The visitor's idea goes up on a slide, five reels show
  how Luna's film was made, the film plays, and the page ends at the invitation list.
- `/studio/` is the night crew: a lighthouse built in clay, filmed at twelve frames a second behind the
  page. It opens with a short film (a mouse strikes a match, lights the great lamp, and a hand swings
  the tower open), then each chapter takes the camera down a floor, where a clay mouse does one job of
  the app: the writer, the voice, the painter, the animator, the editor. Luna's film, as Lanternist
  rendered it in clay, plays in the cinema at the bottom, and the invitation is posted at the jetty.

Both are plain HTML, CSS and ES modules, with no build step.

- `public/`, the lantern show: `stage.js` is the 12 fps clock everything moves on, `art.js` the
  cut-outs, `scenes.js` Luna's seven sets, `story.js` her storyboard, `sketch.js` the visitor's slide
  and `sound.js` the ambience. `tests/test_site.py` keeps the app's facts copied into `story.js` in
  step with the app.
- `public/studio/`, the night crew, on three.js from jsDelivr (pinned in the page's import map):
  `engine.js` renders a frame only when the 12 fps clock moves on, `clay.js` makes plasticine boil
  between frames, `shapes.js`, `props.js`, `crew.js` and `tower.js` build the set, `rooms.js` dresses
  and lights each floor, `rig.js` moves the camera, `foley.js` plays the sound, `intro.js` is the
  opening and `stars.js` the seven hidden stars. It reads Luna's storyboard from `../story.js`.
- `worker.js` keeps the invitation list in D1 (`migrations/`). Cloudflare serves `public/` before the
  Worker runs, so the Worker only answers `/api/waitlist`.

The studio's sounds, voices, music and cast sheets were made on fal, and Luna's film by Lanternist
itself (`lanternist render`, in the clay style, still mode). `studio-assets.json` records each file:
the model, the prompt, and how it was finished. All of it cost about $4.40 on fal, $1.45 of it the
film.

The films are too heavy for git. They live in the R2 bucket `lanternist-website-assets`, served at
`https://assets.lanternist.dev/` (reads allowed from any origin, so the cinema can draw the video in
WebGL). `assets/` mirrors the bucket and is not committed. To replace a film:

```bash
cd site
wrangler r2 object put lanternist-website-assets/studio/film/luna-en.mp4 --file assets/studio/film/luna-en.mp4 \
  --content-type video/mp4 --cache-control "public, max-age=604800" --remote
```

Run it:

```bash
cd site
wrangler d1 migrations apply DB --local   # once
wrangler dev                               # http://127.0.0.1:8787, with a list of its own in .wrangler/
```

Deploy it (the domain is on Cloudflare):

```bash
cd site
wrangler deploy                            # the first time, this creates the database and writes its id here
wrangler d1 migrations apply DB --remote   # right after the first deploy: until then the form can't save
```

Read the list:

```bash
wrangler d1 execute DB --remote --command "SELECT email, idea, lang, created_at FROM waitlist ORDER BY created_at"
```

To move to another domain, change `routes` in `wrangler.jsonc` and the `og:image` addresses in
`public/index.html` and `public/studio/index.html`.

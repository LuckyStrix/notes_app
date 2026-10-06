# daily_brief

An **optional** add-on to notes_app: every morning it gathers your Google Calendar and Tasks, your GitHub repos and a few allowlisted notes-app projects, has a panel of 9router models draft the prose, has an editor model reconcile the drafts, and saves the result as a dated note ("Daily Brief 2026-10-07") in a **Brief** project.

The notes app does not depend on this folder and works identically without it. There is no web UI: you steer it with notes in the Brief project.

## Setup

1. **Start it** (from the repo root, on the machine that runs the notes app):
   ```
   cp daily_brief/.env.example daily_brief/.env      # then fill in the two values below
   docker compose -f daily_brief/docker-compose.yml up -d --build
   ```
   - `GITHUB_TOKEN`: a fine-grained token, **read-only** (Metadata + Contents) on all your repos. Optional: without it only public repos show up.
   - `DB_ROUTER_API_KEY`: from the 9router dashboard (`http://<host>:20128`).
2. **9router** is part of the compose file. Open its dashboard on port 20128, connect your providers, and create an API key. To keep an existing install, copy `~/.9router` into the `router-data` volume. Some providers' logins redirect to `localhost`, which only works from the machine running the container — log in from there.
3. **Google** (one time). In Google Cloud Console create a project, enable the *Google Calendar API* and *Google Tasks API*, create an OAuth client of type *Desktop app*, and set the consent screen's publishing status to **In production** (it is only you; the "unverified app" warning is expected). If you leave it in *Testing*, Google expires the token after 7 days. Then, on any machine with a browser:
   ```
   pip install -r daily_brief/requirements.txt
   DB_DATA_DIR=./token python -m daily_brief auth-google --client-secret client_secret.json
   ```
   and copy `token/google_token.json` into `daily_brief/data/`.
4. The first time it runs it creates the **Brief** project and four notes in it. Set `drafters` and `editor` in **Brief Settings** and you're done. (Until you do, you get the brief without the AI sections.)

## The four notes

| note | who writes it | what it is |
|---|---|---|
| **Brief Instructions** | you | "About me", plus a section each for the Drafter and the Editor. Read on every run. |
| **Brief Settings** | you | `key: value` lines: run time, timezone, panel models, allowlisted notes-app projects, GitHub owner, lookahead. Bad values are ignored and reported in Status. |
| **Brief Control** | you | Type `run` or `dry run` on a line and save. It is picked up within a minute and the note is rewritten with the result (a dry run puts the whole brief there and saves nothing). |
| **Brief Status** | the job | Last run, which models succeeded or failed, lines removed by checks, data problems, settings problems. |

Dated briefs go in a **Briefs** folder. A run later the same day updates that day's note in place.

## How a brief is made

```
Google Calendar + Tasks ─┐
GitHub repos ────────────┼─▶ facts ─▶ render (code): Today / Rest of week / Upcoming / project list
allowlisted notes projects ┘     │
                                 └─▶ drafters (N models, in parallel) ─▶ editor ─▶ guards ─▶ Focus / Outlook / project summaries / Watch-outs
```

- **Facts are rendered by code.** Events, tasks and the week view never pass through a model, so one can't drop or invent an event. Models write only the prose around them.
- **Panel.** Each drafter returns JSON (reasoning first, then the content). The editor sees the facts and every draft, labelled A, B, C (no model names), and writes the final. A model that errors or returns junk is retried once, then recorded in Status; the others carry on. If the editor fails, the first draft is shown and the footer says it's unedited. If every model fails you still get the full factual brief.
- **Guards.** Any date or time a model writes must appear in your data, or that line is dropped (and counted in the footer). A private repo never gets a model-written summary. Project ids must exist.
- **Incomplete briefs are loud.** If Google or GitHub is down (or the Google token expired) the brief is still written, with a `⚠` line at the top, and retried every 30 minutes (up to 4 times) by updating the same note.
- **Catch-up.** If the PC was off at `run_time`, the brief is made as soon as the service is back up that day.

## What leaves your machine

Everything the job gathers is sent to whichever providers 9router routes to, and free providers may log it. That is: calendar event titles/locations, task titles and notes, public repo descriptions and recent commit messages, and the titles and summaries of recent notes in the projects you allowlist. **Private repos contribute only a name and a last-push date.** Nothing else in the notes app is read.

## Guarantees

- **Writes only to the Brief project.** The notes app has no login (the tailnet is the access control), so this is enforced in `notes_api.py`: an explicit list of allowed writes, all scoped to the Brief project, with no DELETE or PUT at all. `tests/test_notes_api.py` pins it down. Reads of other projects are limited to the names in `note_projects`.
- **Own storage.** The Google token and run state live in `daily_brief/data/` (gitignored). Only code and prompts are committed.
- **Notes it writes get indexed** by the notes app like any other (embeddings, keywords). That is why Brief Status is only rewritten when its text changes.

## Command line

```
python -m daily_brief serve            # the scheduler loop (what the container runs)
python -m daily_brief run --dry-run    # print a brief, save nothing
python -m daily_brief run              # make today's brief now
python -m daily_brief auth-google --client-secret client_secret.json
python -m daily_brief healthcheck      # exit 0 if the serve loop is alive
```

Environment (see `.env.example` and the compose file): `DB_NOTES_API_URL`, `DB_ROUTER_URL`, `DB_ROUTER_API_KEY`, `GITHUB_TOKEN`, `DB_DATA_DIR`.

## Tests

```
cd daily_brief && python -m unittest discover -s tests -v
```

The suite needs no network, Docker or Google. It covers settings parsing, the write guard, rendering, the guards on model output, the panel (against a scripted fake router) and the scheduler end to end (against an in-memory notes app).

## Known limits

- The Docker images and the 9router container have not been built or run yet; the Python was exercised against fake notes-app and router servers and the real GitHub API, but not against real Google, real 9router, or the real notes app.
- The date/time guard is deliberately strict: a model writing "1/2 of the work" is read as the date January 2nd and that line is dropped.
- Day-of-week names in model text aren't checked.

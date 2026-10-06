# daily_brief

An **optional** add-on to notes_app: every morning it gathers your Google Calendar and Tasks, your GitHub repos and a few allowlisted notes-app projects, has a panel of 9router models draft the prose, has an editor model reconcile the drafts, and saves the result as a dated note ("Daily Brief 2026-10-07") in a **Brief** project.

The notes app does not depend on this folder and works identically without it.

> Status: scaffold. Nothing is implemented yet.

## Using it

```
docker compose -f daily_brief/docker-compose.yml up -d --build     # from the repo root
```

You work with it through four notes in the Brief project: **Brief Instructions**, **Brief Settings**, **Brief Control** and **Brief Status**. There is no web UI.

## Tests

```
cd daily_brief && python -m unittest discover -s tests -v
```

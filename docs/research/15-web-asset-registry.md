# Project asset registry for Godot 4.4-4.7 (web research, 2026-11-12)

Condensed from the pipeline-web-researcher hand-back (agent had no write tools).

## Summary

Keep a registry tree Godot ignores (`.gdignore`), one small JSON record per asset, one immutable JSON file per version and per note/decision event (ULID names). Parallel worktrees only add new paths → no merge conflicts, no `merge=union` (GitHub web merge ignores it). Godot UIDs are recorded as a lookup key, not the primary ID. SQLite index is a generated, gitignored cache. The review hub writes events through the CLI, never localStorage.

## Godot identity hooks

- `.uid` files (4.4+) exist only for scripts/shaders/custom formats; imported assets keep their UID in `.import`, scenes in their header. Commit `.uid`; move it with the file outside the editor.
- ResourceUID API: `path_to_uid`, `uid_to_path`, `ensure_path`, `id_to_text`, `text_to_id`, `create_id_for_path`... usable headless.
- UID is the wrong primary key: per-file not per-asset, absent for docs/prompts/rejected variants/.gdignore content, exists only after import.
- `.import` files: commit them; editor owns and rewrites them — no custom keys. `uid="uid://…"` readable by regex (format details from memory, verify).
- `set_meta` on resources: wrong place (binary diffs, editor-only, may be lost on reimport).
- EditorImportPlugin is for custom formats; optional EditorPlugin can show registry status in the editor.
- `.gdignore` (empty file) stops import, hides from FileSystem dock, blocks load/preload; dot-prefixed paths never exported; non-resource files need export filters. Sidecars next to assets clutter the dock and may not move with in-editor renames → avoid.

## Storage format

- `merge=union`: git docs warn about random order; GitHub web merges ignore it; duplicates and line edits mangled. Avoid.
- One immutable file per event (`events/<ULID>.json`) → works with every merge path.
- Plain JSON (stdlib): indent 2, sort_keys, ensure_ascii=False, trailing newline. Long prompts in `.prompt.txt`.
- JSON Schema (2020-12) as contract; stdlib CLI checks required fields/enums; full validation in CI with a pinned tool (ask before adding).
- SQLite: generated, gitignored index only.

## Prior art

Unity `.meta` (lost meta = broken refs), Unreal FAssetData (derived index from asset headers), Kitsu status flags (is_done, is_retake, is_feedback_request, is_wip), ShotGrid "Pending Review" default for new Versions, OpenAssetIO entity references, DVC pointer files (md5, size, storage URI). Common model: Asset → Versions (immutable) → Notes (threaded) + Status enum with semantic flags. Godot addons (Global Asset Manager, AssetPlus) do not do review/provenance.

## Binaries

Godot 4.7 VCS docs recommend Git LFS for models, images, audio, fonts, binary resources; set up before first commit. Promoted files in the Godot tree (LFS); candidates in a `.gdignore`'d staging tree (LFS); rejected variants pruned to external content-addressed storage keeping sha256 + URI (DVC style). Export exclusion patterns as backstop.

## Provenance

SPDX ids (CC0-1.0, CC-BY-4.0, OFL-1.1, MIT, LicenseRef-<name>); IPTC digital source type (`trainedAlgorithmicMedia`, `compositeWithTrainedAlgorithmicMedia`); C2PA: record presence/location, keep generator manifests, no own signing; Steam (Jan 2026): disclose pre-generated player-facing AI content → registry must answer "which shipped assets are AI-generated".

## Recommended layout

```
project/
  game/assets/...                 promoted, imported (+ .import / .uid committed)
  registry/
    .gdignore
    schema/{asset,version,event}.schema.json
    assets/<family>/<asset_id>/
      asset.json                  identity + slowly changing fields
      versions/<ULID>.json        immutable
      events/<ULID>.json          immutable note / decision / status / promote
    staging/<asset_id>/<version_ULID>.<ext>
    prompts/<version_ULID>.prompt.txt
  .cache/registry/index.sqlite    generated, gitignored
  .cache/registry/hub.json        generated for the review hub
```

IDs: `asset_id` = slug + short random suffix (`hero_idle-7f3k`), never changes; version/event ids = ULIDs; display numbers v1, v2 computed by sort; `godot_uid` + `res_path` on promote events; `registry doctor` re-resolves moved files via UID then sha256.

Records: asset.json {schema, id, kind, title, family, owner, tags, ship, default_license}; version {schema, id, asset_id, parent_version, files[{role, path, sha256, bytes, storage}], media{...per kind}, provenance{origin, creator, license, source_url, attribution, digital_source_type, human_edited, c2pa}, generation{provider, model, job_id, prompt, prompt_file, negative_prompt, seed, params, inputs[], generated_at}, created_by, created_at}; event {schema, id, asset_id, version_id, type note|decision|status|promote, decision approve|retake|reject, status, reply_to, author, body_md, at}.

Status derived by folding events: draft → wip → pending_review → approved | retake → final, plus rejected, deprecated; new version defaults to pending_review; CLI enforces transitions.

## Storage options

| Option                                       | Parallel worktrees                          | GitHub web merge | Verdict                           |
| -------------------------------------------- | ------------------------------------------- | ---------------- | --------------------------------- |
| Sidecar next to asset                        | ok, but versions+notes in one file conflict | yes              | avoid                             |
| Central catalog                              | constant conflicts                          | painful          | avoid (AloneGodot's 36 manifests) |
| Sharded catalog per family                   | conflicts within family                     | yes              | meh                               |
| Committed SQLite                             | unmergeable                                 | no               | avoid                             |
| Generated SQLite from text                   | n/a                                         | n/a              | use as cache                      |
| JSONL + merge=union                          | random order, duplicates                    | no               | fragile                           |
| Per-asset dir, immutable version/event files | only new paths                              | yes              | recommended                       |

## Risks

`.import` format details and in-editor sidecar moves from memory; UIDs only after editor import (tolerate `godot_uid: null`); event-file count growth (compact on main occasionally); LFS in worktrees and GitHub quotas unverified; Steam wording; C2PA partly read; JSON Schema validator is a dependency to approve.

## Key sources

godotengine.org UID 4.4 article; docs.godotengine.org (ResourceUID, project_organization, exporting_projects, version_control_systems, import_process, EditorImportPlugin, Object); git-scm.com gitattributes; GitHub community #9288; Unity 6.6 asset metadata; Unreal 5.9 Asset Registry; docs.openassetio.org; doc.dvc.org; kitsu.cg-wire.com; Autodesk ShotGrid statuses; spdx.org/licenses; cv.iptc.org digitalsourcetype; C2PA 2.2 spec; PC Gamer / GamingOnLinux on Steam AI disclosure.

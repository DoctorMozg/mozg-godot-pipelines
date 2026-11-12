# Exporting, platforms and shipping (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.7), Godot source at 4.7-stable, Godot PRs, CI tool repos, Steamworks, itch.io, GOG, Google Play, Sentry and IARC docs. Checks are UNTESTED on 4.7.2.

## Executive summary

Export settings are split across two files. `export_presets.cfg` is meant to be committed. Secrets go to `.godot/export_credentials.cfg` (the script key and every option flagged `PROPERTY_USAGE_SECRET`), and signing secrets can also come from `GODOT_*` environment variables, which suits CI. Headless CLI export (`--headless --export-release|--export-debug|--export-pack|--export-patch`) needs an editor binary plus matching templates. Docker images up to `barichello/godot-ci:4.7.2` exist. Shipping-relevant features arrived between 4.3 and 4.7:

- the single-threaded web build became the default (4.3)
- patch PCKs (4.4)
- Windows exports no longer need rcedit, script backtraces work in release builds, and the Logger class arrived (4.5)
- delta-encoded patches, and D3D12 as the default for new Windows projects (4.6)
- export templates can be downloaded per platform (4.7)

Store-side items:

- Google Play has required target API 36 since 2026-08-31. Godot 4.7's Gradle template already targets 36.
- Steam's Content Survey asks you to disclose AI-generated content that ships with the game.
- Godot's MIT notice and third-party notices (COPYRIGHT.txt) must ship with the game.

## 1. Export presets and secrets

- The editor writes two files: `res://export_presets.cfg` (sections `preset.N` and `preset.N.options`) and `res://.godot/export_credentials.cfg`. The credentials file holds `script_encryption_key` and every option flagged `PROPERTY_USAGE_SECRET`. Source: `editor/export/editor_export.cpp` at tag 4.7-stable (https://raw.githubusercontent.com/godotengine/godot/4.7-stable/editor/export/editor_export.cpp). The docs agree: the presets file is safe to commit, and the credentials file must stay out of version control and be copied by hand to new machines (https://docs.godotengine.org/en/stable/tutorials/export/exporting_projects.html, 4.7 docs). Confidence: high.

- Keys written per preset in 4.7: `name, platform, dedicated_server, custom_features, export_filter` (`all_resources|scenes|resources|exclude|customized`), `include_filter, exclude_filter, export_path, patches, patch_delta_encoding, patch_delta_compression_level_zstd, patch_delta_min_reduction, patch_delta_include_filters, patch_delta_exclude_filters, encryption_include_filters, encryption_exclude_filters, seed, encrypt_pck, encrypt_directory, script_export_mode`. In 4.7 source `runnable` is no longer written per preset. It sits in a shared runnable section, and a legacy per-preset key is still read. UNVERIFIED: the version where this moved.

- Files and folders starting with `.` are never exported. Non-resource files such as `*.json` or `*.txt` need the include filter, and the exclude filter removes file types (same exporting_projects page).

- PCK vs ZIP: PCK is the default and is uncompressed. ZIP is compressed and easy to mod, but an exported binary does not auto-load a ZIP, so it needs a launcher that passes `--main-pack` (same page).

- Embedding the PCK uses `binary_format/embed_pck`. On Windows the executable can be at most about 3.89 GB, which leaves about 3.75 GB for the PCK (https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_windows.html).

- Encryption only works with custom templates compiled with `SCRIPT_AES256_ENCRYPTION_KEY`. Encryption include filters are empty by default, so nothing is encrypted until you add one. The key lives inside the binary and can be extracted with effort. A wrong key shows up as `ERR_FILE_CORRUPT` in `file_access_encrypted.cpp` (https://docs.godotengine.org/en/stable/engine_details/development/compiling/compiling_with_script_encryption_key.html).

  ```bash
  openssl rand -hex 32 > godot.gdkey   # keep out of git
  export SCRIPT_AES256_ENCRYPTION_KEY="$(cat godot.gdkey)"; scons platform=windows target=template_release
  ```

- Feature tags:

  - Platform: `windows, linux, macos, android, ios, visionos, web`
  - Build type: `debug, release, template, editor`
  - Architecture: `x86_64, arm64, wasm32`
  - Web host OS: `web_android, web_ios, ...`
  - Threading: `threads, nothreads`
  - Other: `shader_baker, dedicated_server, movie`

  Custom features apply only to exported builds and are ignored when running from the editor. Use `ProjectSettings.get_setting_with_override()` to see per-tag overrides, because `get_setting()` ignores them (https://docs.godotengine.org/en/stable/tutorials/export/feature_tags.html).

## 2. Headless CLI export and templates

```bash
godot --headless --path . --import                        # populate .godot/imported first
godot --headless --path . --export-release "Linux" build/linux/game.x86_64
godot --headless --path . --export-pack "Linux" build/game.pck      # .pck or .zip by extension
godot --headless --path . --export-patch "Linux" build/patch1.pck --patches build/game.pck
```

- What the docs say about these flags (https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html, 4.7):
  - All export flags are editor-only, and the binary must be an editor, not an export template.
  - Relative output paths resolve against the folder holding `project.godot`. The path must include the filename, and its target directory must already exist.
  - `--headless` is required in CI.
  - Unknown arguments are silently ignored.
  - `--install-android-build-template` installs the Android build template and is used together with an export command.
- `--export-patch` and `--patches` (comma-separated) arrived in 4.4 with PR #97118, merged 2024-09-26 (https://github.com/godotengine/godot/pull/97118).
- Templates install to `~/.local/share/godot/export_templates/<ver>.stable/` (`.stable.mono` for C#) (https://github.com/abarichello/godot-ci). 4.7 can download templates per platform or architecture (PR #117072, https://godotengine.org/releases/4.7/).

## 3. Reproducible CI

- Tags on `barichello/godot-ci` include `4.7.2`, `mono-4.7.2` and `latest`, pushed 2026-08-18. The `4.7` tag was pushed 2026-06-22 (Docker Hub API, https://hub.docker.com/v2/repositories/barichello/godot-ci/tags). The repo says to commit `export_presets.cfg` and keep keystores out of git. Preset names are case-sensitive, and the repo cannot export for iOS. Deployment to itch.io uses `BUTLER_API_KEY`, `ITCHIO_USERNAME` and `ITCHIO_GAME` (https://github.com/abarichello/godot-ci). Pin the full tag, never `latest`.
- `chickensoft-games/setup-godot@v2` takes `version` (major.minor.patch, or `global.json`), `use-dotnet` (default true) and `include-templates` (default false). It caches Godot and the templates but does not document its cache keys (https://github.com/chickensoft-games/setup-godot).
- Godot 4.7 stable shipped on about 2026-06-19, 4.7.1 on 2026-07-14 and 4.7.2 on 2026-08-18. These dates come from secondary coverage plus the Docker tag dates (https://godotengine.org/article/maintenance-release-godot-4-7-1/, https://app.cinevva.com/news/2026-06-19-godot-4-7-released). The exact 4.7 date is UNVERIFIED against godotengine.org.

## 4. Desktop

- **Windows signing.** Use SignTool on Windows or `osslsigncode` elsewhere. The preset keys are `codesign/enable`, `codesign/identity` and `codesign/password`. Environment variables `GODOT_WINDOWS_CODESIGN_IDENTITY_TYPE`, `GODOT_WINDOWS_CODESIGN_IDENTITY` and `GODOT_WINDOWS_CODESIGN_PASSWORD` override them. Metadata keys are `application/file_version`, `product_version`, `company_name`, `product_name` and `copyright`. Other keys: `debug/export_console_wrapper` and `application/export_d3d12` (https://docs.godotengine.org/en/stable/classes/class_editorexportplatformwindows.html). Since 4.5 the icon and metadata are edited natively and rcedit is not needed (PR #75950, https://godotengine.org/releases/4.5/). D3D12 has been the default for new Windows projects since 4.6 (PR #113213, https://godotengine.org/releases/4.6/).
- **macOS.** The export is a universal binary, written as `.app`, `.zip` or `.dmg`. A DMG can only be made on macOS. A `.app` exported from Windows loses its executable bit, so prefer `.zip`.
  - Signing: `rcodesign` works from Linux, Windows and macOS, using a PKCS#12 file. Xcode codesign and notarytool work only on macOS.
  - Notarization: the Debugging entitlement must be off. GDExtension needs Disable Library Validation.
  - Environment variables: `GODOT_MACOS_CODESIGN_CERTIFICATE_FILE/_PASSWORD/_PROVISIONING_PROFILE` and `GODOT_MACOS_NOTARIZATION_API_UUID/_API_KEY/_API_KEY_ID/_APPLE_ID_NAME/_APPLE_ID_PASSWORD`.
  - CLI notarization with rcodesign: `rcodesign notary-log`, then `rcodesign staple` (https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_macos.html).
- **Linux.** The export is a binary plus `data.pck`. Official templates exist for x86_64, x86_32, arm64 and arm32. For rv64, ppc64 and loongarch64 you build templates yourself. The docs do not mention AppImage, Flatpak or Snap (https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_linux.html). UNVERIFIED: the minimum glibc of the official templates.
- **Steam Deck review** (https://partner.steamgames.com/doc/steamdeck/compat):
  - The default controller config must reach all content, and glyphs must match the active input device.
  - Text input must open the on-screen keyboard or offer a built-in controller-friendly entry.
  - Resolution should be 1280x800, with 1280x720 also accepted.
  - The smallest text must be at least 9 px tall at 1280x800, and Valve recommends 12 px.
  - The game must reach 30 fps at 800p.
  - The game must not warn that the device is unsupported, and launchers must be fully controller-navigable.
  - Valve tests the Linux build first and falls back to the Windows build under Proton.

## 5. Web

- Single-threaded export has been the default since 4.3. Threaded builds (`variant/thread_support`) need `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp` plus a secure context. Without real headers, the PWA service worker can fake them (`progressive_web_app/ensure_cross_origin_isolation_headers`).
- Only the Compatibility renderer (WebGL 2) works. Godot 4 C# cannot export to web.
- Audio defaults to Sample playback, which is low-latency but has no AudioEffects. Stream playback supports everything but adds latency.
- gzip shrinks the `.wasm` to about a quarter, and itch.io does not gzip on the fly.
- `variant/extensions_support` is needed for GDExtensions on web.

Sources: https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_web.html and https://docs.godotengine.org/en/stable/classes/class_editorexportplatformweb.html. 4.5 added WebAssembly SIMD (https://godotengine.org/releases/4.5/).

## 6. Mobile

- **Android with Gradle.** Turn on `gradle_build/use_gradle_build`, then set `gradle_build/export_format` to AAB. Play has required AAB since August 2021.

  - Release signing uses `keystore/release`, `release_user` and `release_password`, overridable by `GODOT_ANDROID_KEYSTORE_RELEASE_PATH`, `_USER` and `_PASSWORD`. The keystore and key passwords must match.
  - Turn off "Export With Debug" for release builds.
  - Other keys: `version/code`, `version/name`, `package/unique_name`, `permissions/*`.

  Sources: https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_android.html and https://docs.godotengine.org/en/stable/classes/class_editorexportplatformandroid.html.

- At 4.7-stable, the template's `config.gradle` has minSdk 24, targetSdk 36, compileSdk 36, buildTools 36.1.0, NDK 29.0.14206865 and AGP 8.6.1 (https://raw.githubusercontent.com/godotengine/godot/4.7-stable/platform/android/java/app/config.gradle).

- CONFLICT DETECTED: the 4.7 Android export docs list Build-Tools 35.0.1 and NDK r28b, while `config.gradle` at 4.7-stable says 36.1.0 and NDK 29. Trust the source and treat the docs as stale.

- Google Play has required new apps and updates to target API 36 since 2026-08-31. The optional extension ran to 2026-11-01, which has already passed (https://support.google.com/googleplay/android-developer/answer/11926878).

- 4.5 added 16 KB memory page support (.NET needs .NET 9 or later) and an edge-to-edge option. 4.6 added Gradle builds from the Android editor (GABE) and the Storage Access Framework, which removes the need for broad storage permissions (https://godotengine.org/releases/4.5/, https://godotengine.org/releases/4.6/).

- **iOS.** You must export from macOS with Xcode installed. The App Store Team ID (10 characters) and a bundle ID are required. Environment variables: `GODOT_IOS_PROVISIONING_PROFILE_UUID_DEBUG` and `_RELEASE` (https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_ios.html).

## 7. Consoles

The Godot Foundation ships no console ports. W4 Games sells middleware for Switch, Xbox Series and PS5, and third-party porting studios include RAWRLAB, mazette!, Olde Sküül, Tuanisapps, Seaven and Sickhead. Platform NDAs keep console code out of the public repo (https://docs.godotengine.org/en/4.5/tutorials/platform/consoles.html, https://godotengine.org/consoles/index.html). The 4.7 docs URL for this page returned 404. W4's pricing and current terms are UNVERIFIED.

## 8. Steam and other stores

- **GodotSteam.** It moved to Codeberg, and the GitHub repo was archived on 2026-11-10 (https://github.com/GodotSteam/GodotSteam, https://codeberg.org/godotsteam/godotsteam). It ships as a pre-compiled module editor or as a GDExtension, from Releases or the Asset Library. It is MIT-licensed. The current build is 4.24, and Steamworks SDK 1.65 needs GodotSteam 4.21 or later. The Steam overlay may not work in the editor but works in exports. Exactly what the GDExtension flavour lacks compared with the module is UNVERIFIED (godotsteam.com returned 403).
- **Achievements and stats.** These go through the Steamworks ISteamUserStats API via GodotSteam. The exact current call sequence, for example whether `requestCurrentStats` is still needed after SDK 1.61, is UNVERIFIED.
- **Cloud saves.** Auto-Cloud needs no code. Its roots include `WinAppDataRoaming`, `LinuxXdgDataHome` and `MacAppSupport`, root overrides need the Cross-Platform OS restriction, and you set byte and file quotas per user (https://partner.steamgames.com/doc/features/cloud). Godot's `user://` is `%APPDATA%\Godot\app_userdata\<name>` by default, or `%APPDATA%\<custom_user_dir_name>` when `application/config/use_custom_user_dir` is on (https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html). Set a custom user dir so the Auto-Cloud paths stay stable.
- **SteamPipe** (https://partner.steamgames.com/doc/sdk/uploading):
  ```
  "AppBuild" { "AppID" "1000" "Desc" "ci 1.2.3+abc123" "ContentRoot" "../build/windows/" "BuildOutput" "../output/"
    "SetLive" "beta" "Depots" { "1001" { "FileMapping" { "LocalPath" "*" "DepotPath" "." "recursive" "1" } } } }
  ```
  Run it with `steamcmd +login <account> +run_app_build app_build_1000.vdf +quit`. The default branch cannot be set live automatically. For CI, keep `config/config.vdf` between runs so Steam Guard does not ask again. Use one depot per OS.
- **itch.io.** `butler push build/web user/game:html5 --userversion-file VERSION --if-changed`. `--dry-run` previews a push. A channel name containing `win`, `linux`, `mac` or `android` tags the upload automatically, but HTML5 is set by hand on the game page (https://itch.io/docs/butler/pushing.html).
- **GOG and Epic.** GOG uses Pipeline Builder (`pb`, a CLI) or Build Creator, and Pipeline Builder cannot publish straight to the Master branch (https://docs.gog.com/pb-publish-build/, https://docs.gog.com/build-delivery/). Epic uses BuildPatchTool with Organization, Product and Artifact IDs, but the official tutorial was not opened (https://dev.epicgames.com/community/learning/tutorials/z01q/epic-games-store-how-to-upload-your-binaries-using-build-patch-tool). UNVERIFIED: the exact Epic CLI arguments.

## 9. Patching, DLC and versioning

- `ProjectSettings.load_resource_pack(path, replace_files=true)` returns success, and packs loaded later override earlier ones. Call it from an autoload's `_init()` so pre-loaded scenes see the pack (https://docs.godotengine.org/en/stable/tutorials/export/exporting_pcks.html, 4.7).
- Patch PCKs arrived in 4.4: set Base Packs and "Export as Patch". Delta encoding arrived in 4.6 (PR #112011), with zstd level 19 by default and as the recommended maximum. Base packs must be exactly the files the game loads at runtime, in load order. Re-exporting an old version may not be byte-identical, so archive every shipped PCK.
- The version source is `application/config/version` (default `""`, https://docs.godotengine.org/en/stable/classes/class_projectsettings.html). Per-platform fields also exist: Windows `application/file_version` and `product_version`, Android `version/code` and `version/name`. Whether they fall back to `config/version` is UNVERIFIED. To keep one source of truth, have CI stamp them all from one version string plus the git SHA.

## 10. Crash reporting, logging and telemetry

- `debug/file_logging/enable_file_logging` is false, but its `.pc` override is true, so desktop builds log to `user://logs/godot.log` and keep 5 files. Release builds flush stdout only on exit or crash unless `application/run/flush_stdout_on_print` is on.

- Since 4.5 a `Logger` subclass registered with `OS.add_logger` can capture logs, for example for an in-game bug reporter. Script backtraces in release need `debug/settings/gdscript/always_track_call_stacks` (default false).

- Crash backtraces go to stderr and the log file. Official binaries have no debug symbols. `debug/settings/crash_handler/message` sets the text shown on a crash.

  Sources: https://docs.godotengine.org/en/stable/tutorials/scripting/logging.html, the ProjectSettings class page, and PR #91006 (https://godotengine.org/releases/4.5/).

- **Sentry.** sentry-godot is a C++ GDExtension built on sentry-native. SDK 1.x and 2.x need Godot 4.5 or later, and 0.x supports 4.3. It covers Windows, Linux, macOS, Android (Gradle build required), iOS, Web (since 1.4.0) and C# (since 2.0.0, .NET 4.5+). The current version per the docs is 2.5.1. The DSN goes in Project Settings > Sentry > Options and is saved to `project.godot`. Other options: `before_send`, `attach_log`, `godot_logger.log_mask`, and user feedback. Native symbols require custom templates with symbols (https://docs.sentry.io/platforms/godot/, https://github.com/getsentry/sentry-godot).

- **GDPR.** Personal data needs a lawful basis (Art. 6). Consent must be freely given and as easy to withdraw as to give (Art. 7), and children's data has its own rules (Art. 8) (https://eur-lex.europa.eu/eli/reg/2016/679/oj). Make telemetry opt-in, scrub data in `before_send`, and keep the DSN out of public forks if quota abuse is a concern. Treating a Sentry DSN as public-but-abusable is an opinion, not a documented rule.

## 11. Release checklist items

- Steam Content Survey: disclose pre-generated and live-generated AI content that players consume, and describe guardrails for live generation. AI used only to work faster is "not the focus" of the survey (https://partner.steamgames.com/doc/gettingstarted/contentsurvey, undated page).
- IARC: one free questionnaire produces ESRB, PEGI, USK, ClassInd and other ratings for participating stores, including Google Play, Nintendo eShop and Microsoft Store. Reported participants also include the Epic and PlayStation stores (https://www.globalratings.com/milestones, and Wikipedia, which is secondary). Steam does not participate, which is UNVERIFIED.
- Licences: ship Godot's MIT text, including "Copyright (c) 2014-present Godot Engine contributors." and "Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur." Also ship third-party notices from `COPYRIGHT.txt` or `Engine.get_copyright_info()` / `get_license_info()`, plus credits for every asset. iOS has no visible print log (https://docs.godotengine.org/en/stable/about/complying_with_licenses.html). GodotSteam and sentry-godot carry their own licences.
- Accessibility: screen reader support via AccessKit (4.5, experimental) and landmark navigation (4.7, PR #114449). Valve's 9 px minimum text rule applies on Deck.

## Version-specific features

| Feature                                                                 | Version                | Source                 |
| ----------------------------------------------------------------------- | ---------------------- | ---------------------- |
| Single-threaded web default, Web Audio Sample playback                  | 4.3                    | exporting_for_web.html |
| Patch PCKs, `--export-patch`, `--patches`                               | 4.4                    | PR #97118              |
| Windows icon and metadata without rcedit                                | 4.5                    | PR #75950              |
| Release script backtraces (`always_track_call_stacks`), custom `Logger` | 4.5                    | PR #91006              |
| Android 16 KB pages, edge-to-edge                                       | 4.5                    | PR #106358, #107742    |
| visionOS export, shader baker, web WASM SIMD                            | 4.5                    | PR #105628, #102552    |
| Screen reader (AccessKit, experimental)                                 | 4.5                    | PR #76829              |
| sentry-godot 1.x/2.x minimum engine                                     | 4.5                    | getsentry/sentry-godot |
| Delta-encoded patch PCKs                                                | 4.6                    | PR #112011             |
| D3D12 default for new Windows projects                                  | 4.6                    | PR #113213             |
| Android editor Gradle builds (GABE), SAF                                | 4.6                    | PR #111732, #112215    |
| Per-platform template download, Android splash in export options        | 4.7                    | PR #117072, #114671    |
| HDR output on desktop and iOS, landmark navigation                      | 4.7                    | releases/4.7           |
| Android template targetSdk 36 / minSdk 24                               | 4.7-stable             | config.gradle          |
| `runnable` stored in a shared section                                   | ≤4.7 (UNVERIFIED when) | editor_export.cpp      |

## Checkable rules an agent should follow

1. `export_presets.cfg` is tracked in git, and `.godot/` (which holds `export_credentials.cfg`) is git-ignored.
1. No `password`, `keystore/*_password`, `codesign/password` or `script_encryption_key` value is non-empty in `export_presets.cfg`.
1. No `*.keystore`, `*.jks`, `*.p12`, `*.pfx`, `*.p8` or `godot.gdkey` file is tracked.
1. Every preset name used in a CI or Makefile export command exists exactly, matching case, in `export_presets.cfg`.
1. Every preset's `export_path` is relative and inside a git-ignored build directory.
1. Release presets have Android `export with debug` off, macOS Debugging entitlement off, and Windows `debug/export_console_wrapper` set as intended.
1. An Android release preset has `gradle_build/use_gradle_build=true`, AAB format, and `gradle_build/target_sdk` empty or at least 36.
1. `package/unique_name` (Android) and the macOS/iOS bundle ID do not contain `$genname` or `noname`.
1. A web preset either has threads off, or has the PWA isolation-headers option on or a documented host that sends COOP/COEP.
1. The web preset's project uses `rendering/renderer/rendering_method.web` = `gl_compatibility`, and the project has no C# when a web preset exists.
1. `application/config/version` is non-empty and matches the Windows `file_version`/`product_version` and Android `version/name`. `version/code` increases with each release.
1. `encrypt_pck=true` only together with a custom template path and non-empty encryption include filters.
1. The CI Godot version (Docker tag, setup-godot `version`) equals the project's pinned version, and no CI job uses the `latest` tag.
1. CI runs `--headless --import` before export, and judges success by the output file and log, not the exit code alone.
1. A licences/credits file or scene contains Godot's MIT text and the third-party notices, and every asset in the asset registry carrying an attribution licence appears in credits.
1. `application/config/use_custom_user_dir` is true with a stable `custom_user_dir_name` when Steam Auto-Cloud is configured.
1. File logging (`.pc`) is left on, and `always_track_call_stacks` is decided explicitly in release.
1. A Sentry DSN in `project.godot` comes with an opt-in consent gate in code (grep for the init path) and a `before_send` scrubber.
1. Every shipped base PCK is archived next to its version tag before any delta patch is built against it.
1. Steam VDFs never set `SetLive` to `default`, and every depot has a `FileExclusion` for `*.pdb`, `*.dSYM` and logs.
1. GDExtension `.gdextension` files list libraries for every exported platform and architecture.
1. A release checklist file records the AI-disclosure answers, IARC/age rating, and Deck checks (9 px text, glyphs).

## What a tool could check automatically

- **Preset lint.** Parse `export_presets.cfg` as INI with Godot's Variant syntax for strings, `PackedStringArray` and booleans. Check that names are unique, platform names are valid, `export_path` is set, filters are sane, and rules 5 to 12 hold.
- **Secrets scan.** Flag non-empty secret-like keys in the presets file, tracked key and certificate files, and `GODOT_*_PASSWORD` values written literally in CI YAML.
- **Template presence.** Check `~/.local/share/godot/export_templates/<godot --version minus hash>/` holds the files each preset platform needs.
- **Dry-run export per preset.** Run `--headless --export-pack <preset> scratch/x.pck` into a temp directory, parse the log for `ERROR:` lines and missing-template messages, then delete the output, since disk space is tight.
- **PCK listing.** Read the PCK header (magic `GDPC`, format version, file table) in stdlib Python. Assert that no `.godot/`, `*.import` sources, test folders, `addons/*/tests`, `.env` or `*.md` slipped in, and diff the listing between releases. UNVERIFIED: the exact header layout for 4.7, so read it from `core/io/file_access_pack.cpp`.
- **Patch check.** Confirm the PCKs in `patches=` exist and their hashes match the archived release manifest.
- **Licence/credits completeness.** Every `addons/*` LICENSE and every attribution-required asset appears in the credits file, and the Godot MIT strings are present.
- **Version stamp consistency** (rule 11), plus a JSON or `build_info` file containing git SHA, Godot version, preset and date.
- **Store manifests.** Validate Steam VDF depots against built directories, and butler channel names against platforms.
- **Doctor.** Detect optional tools: rcodesign, osslsigncode, JDK 17+, Android SDK, butler, steamcmd.

## Pitfalls

- Exporting with an export-template binary instead of the editor binary, or without `--headless` in CI.
- Output paths resolve against `project.godot`, not the current directory, and the output directory must already exist.
- A typo in an unknown CLI argument is silently ignored.
- A fresh clone has no `export_credentials.cfg`, so exports run unsigned or unencrypted without warning unless the `GODOT_*` environment variables are set.
- Encryption with stock templates gives `ERR_FILE_CORRUPT` at runtime, and empty encryption filters encrypt nothing.
- A ZIP main pack is not auto-loaded. Embedded PCKs on Windows are limited to about 3.75 GB.
- Threaded web builds go blank on hosts without COOP/COEP headers, and itch.io does not gzip.
- Sample audio on web drops AudioEffects.
- A `.app` exported from Windows loses its executable bit. DMG output needs macOS, and notarization fails if the Debugging entitlement is on.
- Android: the keystore and key passwords must match, AAB requires Gradle, and Play now requires API 36. The Android docs lag behind the real SDK and NDK versions.
- Delta patches break if the base PCKs are re-exported instead of archived.
- Official templates have no symbols, so native crash reports need custom templates.
- SteamPipe cannot auto-set-live the default branch, and Steam Guard blocks fresh CI logins.
- GodotSteam's GitHub repo is archived, so update links and the Asset Library source to Codeberg.

## Sources

- Godot 4.7 docs: exporting_projects, command_line_tutorial, exporting_pcks, exporting_for\_{web,windows,macos,linux,android,ios,dedicated_servers}, feature_tags, logging, data_paths, complying_with_licenses, compiling_with_script_encryption_key, class pages (ProjectSettings, EditorExportPlatform{Windows,Web,Android}). All under https://docs.godotengine.org/en/stable/ (4.7).
- Godot source at 4.7-stable: `editor/export/editor_export.cpp` and `platform/android/java/app/config.gradle`.
- PRs #97118 and #75950. Release pages https://godotengine.org/releases/4.5/, /4.6/, /4.7/.
- Console page, 4.5 docs: https://docs.godotengine.org/en/4.5/tutorials/platform/consoles.html
- CI: https://github.com/abarichello/godot-ci, Docker Hub tags API, https://github.com/chickensoft-games/setup-godot
- GodotSteam: https://codeberg.org/godotsteam/godotsteam and the archived https://github.com/GodotSteam/GodotSteam
- Sentry: https://docs.sentry.io/platforms/godot/ and https://github.com/getsentry/sentry-godot
- Steamworks: https://partner.steamgames.com/doc/sdk/uploading, /doc/features/cloud, /doc/steamdeck/compat, /doc/gettingstarted/contentsurvey
- itch.io butler: https://itch.io/docs/butler/pushing.html
- GOG: https://docs.gog.com/build-delivery/ and https://docs.gog.com/pb-publish-build/
- Google Play target API: https://support.google.com/googleplay/android-developer/answer/11926878
- IARC: https://www.globalratings.com/milestones
- GDPR: https://eur-lex.europa.eu/eli/reg/2016/679/oj

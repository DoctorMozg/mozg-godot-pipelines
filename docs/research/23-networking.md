# Networking and multiplayer (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.x/latest), the 4.0–4.7 release notes, Godot PRs and service/addon repos. Probes and GDScript examples are UNTESTED on 4.7.2.

## Executive summary

- The core multiplayer API has changed little since 4.2. The main changes were in 4.0 (the rework), 4.1 ("watched", meaning on-change, delta properties) and 4.2 (the `ReplicationMode` enum). The release notes for 4.3 through 4.7 list no headline networking changes. The version-sensitive items for this range are around the network layer: physics interpolation (4.3/4.4), Jolt (4.4, the default for new 3D projects in 4.6), single-threaded web export (4.3), and GodotSteam needing 4.24+ builds for 4.7.
- The built-in tools are authority-based and server-authoritative by default. `SceneMultiplayer.allow_object_decoding=false` and the `@rpc` default of `"authority"` are safe. `server_relay=true` is a convenience default that a dedicated authoritative server should review.
- The engine has no prediction, rollback, lag compensation or network simulation. netfox (MIT, active) is the main addon. godot-rollback-netcode and Delta Rollback (both MIT) need deterministic simulation, and Godot's built-in physics is not deterministic.
- A CLI kit can check a lot without running anything: `@rpc` annotations, `.tscn` replication configs, export presets and project settings. It can also launch two `--headless` instances and judge the run by its log lines.

## 1. High-level API: MultiplayerAPI, SceneMultiplayer, peers, authority

- The default MultiplayerAPI implementation is `SceneMultiplayer`. You assign a peer to it (`ENetMultiplayerPeer.create_server/create_client`) and stop networking with `OfflineMultiplayerPeer`. The server's peer ID is always 1. [docs, high_level_multiplayer, 4.x](https://docs.godotengine.org/en/4.5/tutorials/networking/high_level_multiplayer.html)
- `ENetMultiplayerPeer.create_server(port, max_clients=32, max_channels=0, in_bandwidth=0, out_bandwidth=0)`. `max_clients` can be up to 4095. [ENetMultiplayerPeer, latest](https://docs.godotengine.org/en/latest/classes/class_enetmultiplayerpeer.html)
- SceneMultiplayer defaults: `allow_object_decoding=false`, `auth_callback=Callable()`, `auth_timeout=3.0`, `max_sync_packet_size=1350`, `max_delta_packet_size=65535`, `refuse_new_connections=false`, `server_relay=true`. The authentication flow uses `send_auth`, `complete_auth` and the signals `peer_authenticating` / `peer_authentication_failed`. [SceneMultiplayer, latest](https://docs.godotengine.org/en/latest/classes/class_scenemultiplayer.html)
- Authority is the server by default. Set it per node with `set_multiplayer_authority(id)`. `multiplayer.get_remote_sender_id()` returns 0 outside an RPC, and the value "may be lost when code execution is delayed (such as with GDScript's `await`)". [MultiplayerAPI, latest](https://docs.godotengine.org/en/latest/classes/class_multiplayerapi.html)

### @rpc

- Signature: `@rpc(mode="authority", sync="call_remote", transfer_mode="reliable", transfer_channel=0)`. The first three arguments can come in any order. The channel must be the 4th argument, so all three before it must be given. `transfer_mode` is `unreliable`, `unreliable_ordered` or `reliable`. An `@rpc` method cannot receive objects whose `_init()` has required parameters. [@GDScript, latest](https://docs.godotengine.org/en/latest/classes/class_%40gdscript.html)
- Matching rule: "all RPCs must be declared on both the client scripts and the server scripts". The checksum covers the annotation, the name, the return type and the NodePath. Argument lists are not checked, and the NodePath (node names) must match on every peer. [high_level_multiplayer](https://docs.godotengine.org/en/4.5/tutorials/networking/high_level_multiplayer.html)

```gdscript
@rpc("any_peer", "call_remote", "reliable")
func request_move(dir: Vector2) -> void:
    var sender := multiplayer.get_remote_sender_id()   # read before any await
    if not multiplayer.is_server() or sender != player_id:
        return
    if not dir.is_finite() or dir.length() > 1.0:
        return
    _input_dir = dir

@rpc("authority", "call_local", "unreliable_ordered", 1)
func sync_state(pos: Vector2) -> void:
    position = pos
```

## 2. MultiplayerSpawner and MultiplayerSynchronizer

- **Spawner.** Only scenes added as direct children of `spawn_path` replicate, and they replicate from the authority. `spawn_limit=0` means unlimited. `spawn_function` runs on all peers, and the node it returns must not be passed to `add_child()`. `spawned` and `despawned` fire only on remote peers. `clear_spawnable_scenes()` does not despawn instances that already exist on remote peers. [MultiplayerSpawner, latest](https://docs.godotengine.org/en/latest/classes/class_multiplayerspawner.html)
- **Synchronizer.** It syncs from the multiplayer authority to remote peers. Defaults: `root_path=".."`, `replication_interval=0.0`, `delta_interval=0.0` (0 means every network frame), `public_visibility=true`. Per-peer visibility uses `add_visibility_filter(Callable)`, `set_visibility_for(peer, bool)` and `update_visibility()`. "Synchronization is not supported for Object type properties, like Resource". RIDs and instance IDs also do not work. [MultiplayerSynchronizer, latest](https://docs.godotengine.org/en/latest/classes/class_multiplayersynchronizer.html)
- **SceneReplicationConfig modes.** `NEVER`. `ALWAYS` sends unreliably every process. `ON_CHANGE` sends reliably when the value changes. `property_set_sync` and `property_set_watch` are deprecated in favour of `property_set_replication_mode`. [SceneReplicationConfig, latest](https://docs.godotengine.org/en/latest/classes/class_scenereplicationconfig.html)
- **Watched-property limits.** Watched (on-change) properties are deep-duplicated and compared at each delta interval. The limit is 64 watched properties per synchronizer, and the 64 KB delta packet limit is configurable. Source: [PR #75467 (Faless, merged 2023-05-24, milestone 4.1)](https://github.com/godotengine/godot/pull/75467). UNVERIFIED: whether the 64-property cap still holds in 4.7.
- **Usual pattern.** The server owns the character. A child input node is given to the owning peer, and the server spawns players through the spawner. [Faless, "Scene replication", 2023-02-23](https://godotengine.org/article/multiplayer-in-godot-4-0-scene-replication/)

```gdscript
@export var player := 1:
    set(id):
        player = id
        $PlayerInput.set_multiplayer_authority(id)
```

## 3. Transports and the web

- **ENet** (UDP only). Forward the port as UDP. Android exports need the `INTERNET` permission. [high_level_multiplayer](https://docs.godotengine.org/en/4.5/tutorials/networking/high_level_multiplayer.html)
- **WebSocket.** In a web export it is client only: "Low-level networking is not implemented". Only HTTP, the WebSocket client and WebRTC work in the browser. Threaded web builds need COOP `same-origin` and COEP `require-corp` headers in a secure context. [exporting_for_web, latest](https://docs.godotengine.org/en/latest/tutorials/export/exporting_for_web.html). Single-threaded web export returned in [4.3](https://godotengine.org/releases/4.3/).
- **WebRTC.** Built in on the web. Native platforms need the external webrtc-native GDExtension. A signaling server is required, usually over WebSocket. [webrtc, latest](https://docs.godotengine.org/en/latest/tutorials/networking/webrtc.html). STUN/TURN is not covered on that page. UNVERIFIED: official guidance on STUN/TURN.

## 4. Topologies and dedicated servers

- **Topologies.** Client-server uses a dedicated server. A listen server is a host that also plays, so use `call_local`. P2P uses a WebRTC mesh. The high-level API always routes through a server (ID 1) unless you use a mesh. With `server_relay` the server forwards traffic between clients. [SceneMultiplayer](https://docs.godotengine.org/en/latest/classes/class_scenemultiplayer.html)
- **Dedicated server.** `--headless` works on every platform since 4.0, so 3.x-style server binaries are not needed. Export with "Export as dedicated server" on the preset's Resources tab, which adds the `dedicated_server` feature tag. Resource options are Strip Visuals (the recommended default), Keep, and Remove; a scene that references a removed resource fails to load. Detect server mode with `OS.has_feature("dedicated_server")`, `DisplayServer.get_name() == "headless"` or a user argument (`OS.get_cmdline_user_args()`). Use an export template rather than the editor binary. Run it under systemd and enable `application/run/flush_stdout_on_print` so logs reach journald; Docker is an option for scaling. [exporting_for_dedicated_servers, latest](https://docs.godotengine.org/en/latest/tutorials/export/exporting_for_dedicated_servers.html)

## 5. Lag handling and rollback

- **Engine.** There is no built-in prediction, reconciliation, lag compensation or snapshot interpolation, per the class docs above. Physics interpolation (2D in 4.3, 3D in 4.4) smooths rendering between physics ticks only. [4.4 notes](https://godotengine.org/releases/4.4/)
- **netfox** (foxssake, MIT). It supports Godot 4.x, though its examples target 4.1. Nodes: `NetworkTime`, `RollbackSynchronizer`, `StateSynchronizer`, `TickInterpolator`. It does client-side prediction and server reconciliation. netfox.extras adds a NetworkSimulator, and netfox.noray handles NAT. The latest release found is v1.35.3 (23 Nov, probably 2025). [docs](https://foxssake.github.io/netfox/latest/), [releases](https://github.com/foxssake/netfox/releases). UNVERIFIED: any 2026 release.
- **godot-rollback-netcode** (Snopek Games, MIT). Godot 4 build 1.0.0-alpha, Asset Library entry targeting 4.2, submitted 2024-05-04. [asset 2450](https://godotengine.org/asset-library/asset/2450), [GitLab](https://gitlab.com/snopek-games/godot-rollback-netcode). UNVERIFIED: whether it is still maintained.
- **Delta Rollback** (BimDav, MIT). A C++ GDExtension port of Snopek's addon. The newest version seen is 0.11.0, with no release date confirmed. [GitLab](https://gitlab.com/BimDav/delta-rollback), [author's article](https://medium.com/@david.dehaene/delta-rollback-new-optimizations-for-rollback-netcode-7d283d56e54b). UNVERIFIED: its status on 4.7.
- **Determinism.**
  - Godot's built-in physics uses floats and is not deterministic. Godot cannot manually step physics; netfox's docs say so, and the netfox caveats page could not be fetched (404).
  - SG Physics 2D (fixed point) is the usual pairing for lockstep or rollback.
  - Godot Rapier claims cross-platform determinism at a performance cost, but only for the physics server. Scene tree state, input and scripts can still diverge. [Rapier determinism](https://godot.rapier.rs/docs/documentation/determinism), [GDQuest glossary](https://www.gdquest.com/library/glossary/deterministic_simulation)
  - Jolt has been the default for new 3D projects since 4.6, and existing projects keep their engine. [4.6 notes](https://godotengine.org/releases/4.6/). UNVERIFIED: whether Godot's Jolt integration is deterministic.

## 6. Services, NAT and relay

| Service              | What                                                                                   | Licence                          | Status (checked 2026-11-13)                                                                                                                                                                       |
| -------------------- | -------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GodotSteam           | Steamworks module or GDExtension with a MultiplayerPeer implementation                 | MIT                              | Moved to Codeberg; GitHub archived 2026-11-10. Build 4.24, SDK 1.65 (needs ≥4.21). 4.7 changed a header, so older GodotSteam builds break. [Codeberg](https://codeberg.org/GodotSteam/GodotSteam) |
| EOSG (3ddelano)      | Epic Online Services, including P2P via `HP2P`                                         | MIT                              | Godot 4.2+, EOS SDK 1.19.1.2 [GitHub](https://github.com/3ddelano/epic-online-services-godot)                                                                                                     |
| W4 Cloud             | Lobbies, matchmaking, WebRTC P2P                                                       | AGPLv3 core, paid hosted service | Launched 2024-10-10 [blog](https://w4games.com/blog/w4-games-news-1/w4-cloud-launches-today-44). Product page returns 404, so current status is UNVERIFIED.                                       |
| Nakama (Heroic Labs) | Server plus client; `NakamaMultiplayerBridge` plugs into the high-level API            | Apache-2.0                       | Godot 4.0+ [GitHub](https://github.com/heroiclabs/nakama-godot)                                                                                                                                   |
| Talo                 | Backend: accounts, saves, websocket channels, presence; no matchmaking or relay listed | MIT, self-hostable               | Free under 10k players [trytalo.com](https://trytalo.com/)                                                                                                                                        |
| noray                | NAT punch-through plus UDP relay (TCP control protocol)                                | MIT                              | Needs bun ≥1.3 [GitHub](https://github.com/foxssake/noray)                                                                                                                                        |

ENet has no NAT traversal of its own. Use port forwarding, noray, Steam, EOS, or WebRTC with STUN/TURN. UNVERIFIED: whether Steam Datagram Relay is exposed through GodotSteam's peer.

## 7. Security and serialization

- Never trust the client. Every `any_peer` RPC must check `get_remote_sender_id()` against the owner and clamp or validate its arguments. `authority` mode blocks non-authority callers. [@GDScript](https://docs.godotengine.org/en/latest/classes/class_%40gdscript.html)
- `bytes_to_var_with_objects`: "Deserialized object can contain code which gets executed. Do not use this option if the serialized object comes from untrusted sources" (remote code execution). Use `var_to_bytes`/`bytes_to_var` or a hand-packed `PackedByteArray`. Keep `allow_object_decoding=false`. [@GlobalScope](https://docs.godotengine.org/en/latest/classes/class_%40globalscope.html), [SceneMultiplayer](https://docs.godotengine.org/en/latest/classes/class_scenemultiplayer.html)
- Bandwidth:
  - `reliable` mode has a "significant" cost. Send continuous state as `unreliable_ordered` on its own channel.
  - The 1350-byte `max_sync_packet_size` default sits close to a typical MTU.
  - The network profiler counts only high-level API bytes, not protocol overhead ([issue #91869](https://github.com/godotengine/godot/issues/91869)).

## 8. Testing locally and in CI

- Editor: Debug > Customize Run Instances runs N instances, each with its own launch arguments; documented from 4.3. [4.4 docs](https://docs.godotengine.org/en/4.4/tutorials/scripting/debug/overview_of_debugging_tools.html)
- CI: `godot --headless --path . -- --server &` plus a client instance. Judge the run by explicit log lines.
- Latency and loss simulation:
  - LaggyMultiplayerPeer (GDExtension, Godot ≥4.4) wraps any peer. [ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Fricmzn%2Flaggy-multiplayer-peer)
  - netfox NetworkSimulator. [docs](https://foxssake.github.io/netfox/latest/netfox.extras/guides/network-simulator)
  - Linux `tc netem` is a standard OS tool and not Godot-specific.
- ENet statistics come from `ENetPacketPeer.get_statistic`. [Godot 4.0 report 3](https://godotengine.org/article/multiplayer-changes-godot-4-0-report-3/)

## Version table

| Feature                                                                                                | Version                                                    | Source                                                                                                                                                                                                                          |
| ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `@rpc`, SceneMultiplayer, Spawner/Synchronizer, `--headless` on all platforms, dedicated-server export | 4.0                                                        | [dedicated servers doc](https://docs.godotengine.org/en/latest/tutorials/export/exporting_for_dedicated_servers.html), [scene replication article](https://godotengine.org/article/multiplayer-in-godot-4-0-scene-replication/) |
| Watched (on-change) properties, `delta_interval`, `delta_synchronized`                                 | 4.1                                                        | [PR #75467](https://github.com/godotengine/godot/pull/75467)                                                                                                                                                                    |
| `ReplicationMode` enum, `property_set_replication_mode` (sync/watch deprecated)                        | 4.2 (absent from the 4.1 docs)                             | [4.1](https://docs.godotengine.org/en/4.1/classes/class_scenereplicationconfig.html) vs [4.2](https://docs.godotengine.org/en/4.2/classes/class_scenereplicationconfig.html)                                                    |
| 2D physics interpolation; single-threaded web export                                                   | 4.3                                                        | [4.3 notes](https://godotengine.org/releases/4.3/), [4.4 notes](https://godotengine.org/releases/4.4/)                                                                                                                          |
| Customize Run Instances                                                                                | documented in 4.3 (UNVERIFIED: whether it existed earlier) | [4.3 docs](https://docs.godotengine.org/en/4.3/tutorials/scripting/debug/overview_of_debugging_tools.html)                                                                                                                      |
| 3D physics interpolation; Jolt as an experimental option                                               | 4.4                                                        | [4.4 notes](https://godotengine.org/releases/4.4/)                                                                                                                                                                              |
| 3D interpolation moved into SceneTree; WASM SIMD on web                                                | 4.5                                                        | [4.5 notes](https://godotengine.org/releases/4.5/)                                                                                                                                                                              |
| Jolt default for new 3D projects                                                                       | 4.6                                                        | [4.6 notes](https://godotengine.org/releases/4.6/)                                                                                                                                                                              |
| Header change that breaks older GodotSteam                                                             | 4.7                                                        | [GodotSteam](https://codeberg.org/GodotSteam/GodotSteam)                                                                                                                                                                        |

UNVERIFIED: the 4.5–4.7 release pages list no multiplayer API changes. The full changelogs were not read.

## Checkable rules an agent should follow

1. Every `@rpc("any_peer"…)` function reads `multiplayer.get_remote_sender_id()` and checks it before acting.
1. No `await` comes before the `get_remote_sender_id()` read in an RPC.
1. `any_peer` RPCs that change game state check `multiplayer.is_server()` or the authority.
1. `@rpc` with a channel argument has exactly four arguments, and no argument value repeats.
1. Continuous-state RPCs (names like `*_state`, `*_pos`, `*_input`) are not `reliable`.
1. The same `@rpc` method names exist on every script variant used by client and server; there are no `if server` script swaps.
1. No `bytes_to_var_with_objects` or `var_to_bytes_with_objects` on network data.
1. `allow_object_decoding` is never set to true.
1. Dedicated authoritative servers set `server_relay = false` unless clients need to message each other (review item).
1. Networked nodes created at runtime are added as direct children of a spawner's `spawn_path`, or use `add_child(node, true)` so names stay readable and match.
1. The node returned by `spawn_function` is not passed to `add_child()`.
1. Every scene in a spawner's spawnable list exists on disk (`res://` path resolves).
1. Synchronizer property paths resolve to existing node properties, and none is Object, Resource or RID typed.
1. Watched (`ON_CHANGE`) properties per synchronizer number at most 64.
1. Server-only code is gated by `OS.has_feature("dedicated_server")`, a headless check or a user arg, not by OS name.
1. A server export preset exists with dedicated-server mode or the `dedicated_server` feature.
1. Android presets enable the INTERNET permission when the project uses any networking class.
1. Web presets do not use ENet or `create_server` for WebSocket; the web build uses WebSocket client or WebRTC only.
1. A native WebRTC build ships the webrtc-native GDExtension.
1. `application/run/flush_stdout_on_print=true` for server builds.
1. An authentication callback (`auth_callback`) or equivalent handshake is set for public servers.
1. Rollback projects do not use built-in physics bodies inside rollback ticks, or document that determinism is not required.
1. Each pinned networking addon records its version and the Godot version it targets.

## What a tool could check automatically

- **GDScript scan** (`**/*.gd`): parse `@rpc(...)` arguments for rules 1–5. Grep for `bytes_to_var_with_objects`, `allow_object_decoding\s*=\s*true` and `server_relay`. Flag `get_remote_sender_id` that appears after `await` inside the same function.
- **Scene scan** (`**/*.tscn`): `[node type="MultiplayerSpawner"]` → `spawn_path`, plus the `_spawnable_scenes` list resolved on disk. `type="MultiplayerSynchronizer"` → `replication_config` sub-resource with `properties/N/path`, `/spawn`, `/replication_mode`; count `replication_mode = 2` per config. These key names are from memory, so confirm them against a 4.7-saved file (UNVERIFIED).
- **Export presets** (`export_presets.cfg`): a server preset (dedicated-server resource mode or `custom_features` containing `dedicated_server`); `permissions/internet` on Android presets; the web preset's thread setting compared against hosting headers. Key names are UNVERIFIED and should be checked against a 4.7 file.
- **project.godot**: `application/run/flush_stdout_on_print`, `physics/3d/physics_engine` (Jolt vs Godot), physics tick rate, and interpolation settings.
- **Addons**: read `addons/*/plugin.cfg` versions (netfox, godotsteam, nakama, EOSG) and compare against a dated compatibility table, for example GodotSteam < 4.24 on 4.7.
- **Runtime probe**:
  1. Start `godot --headless --path P -- --server --port X` and a client with `-- --client 127.0.0.1:X`, both with a timeout.
  1. Require the log lines `peer_connected`, a spawn, a sync, and one explicit summary line.
  1. Optionally run under `tc netem delay 100ms loss 5%` (Linux, root) or LaggyMultiplayerPeer.
  1. Fail on `ERROR:` lines that contain `rpc`, `checksum` or `node not found`.
- **Doctor**: report the presence of webrtc-native, the Godot binary version, and `tc` availability.

## Pitfalls

- RPC fails because node names differ (`@Node@123`) or because a client-only or server-only script lacks the `@rpc` method. [high_level_multiplayer](https://docs.godotengine.org/en/4.5/tutorials/networking/high_level_multiplayer.html)
- Sender ID is 0 after an `await`.
- Syncing Resources or Objects silently does not work.
- A node spawned under a grandchild of `spawn_path` is not replicated.
- `clear_spawnable_scenes()` leaves remote instances alive.
- Port forwarded as TCP instead of UDP; INTERNET permission missing on Android.
- A web build tries to use ENet or a WebSocket server; threaded web build served without COOP/COEP.
- Built-in physics used inside rollback, which desyncs.
- Network profiler numbers mistaken for wire bandwidth.
- `server_relay` changed while peers are connected leads to "unexpected behaviors". [SceneMultiplayer](https://docs.godotengine.org/en/latest/classes/class_scenemultiplayer.html)
- Old GodotSteam binaries break on 4.7.
- The lobby demo code "aren't designed to run on a dedicated server".

## Risks and uncertainties

- CONFLICT DETECTED: none found between primary sources.
- UNVERIFIED:
  - Networking changes in 4.5–4.7 beyond the release highlights.
  - The 64-watched-property cap in 4.7.
  - Exact `.tscn` and `export_presets.cfg` key names.
  - W4 Cloud's current status and pricing.
  - Maintenance of godot-rollback-netcode and Delta Rollback on 4.7.
  - netfox releases in 2026.
  - Determinism of Godot's Jolt integration.
  - GodotSteam's support for Steam Datagram Relay.
- Some facts come from single sources: noray maturity, LaggyMultiplayerPeer (read via ecosyste.ms, not the repository), and Talo's pricing.

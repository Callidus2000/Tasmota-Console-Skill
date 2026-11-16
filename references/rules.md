# Tasmota Rules: safe workflow

Sources: [Rules](https://tasmota.github.io/docs/Rules/), [Commands: Rules](https://tasmota.github.io/docs/Commands/#rules), and [15.1.0 rule implementation](https://github.com/arendst/Tasmota/blob/v15.1.0/tasmota/tasmota_xdrv_driver/xdrv_10_rules.ino). Firmware build options and version determine what exists. This reference is not a full parser or proof of correctness.

## Inventory and backup

Query `Status 2`, `Rule1`, `Rule2`, `Rule3` and relevant safe device settings. Rule sets may already be enabled or perform actions immediately on the next event. Each `RuleN` result includes its text and mode metadata on 15.1.0. Identify existing `Var`, `Mem`, `RuleTimer`, timers, triggers and interactions with the outside world before choosing identifiers. Never assume an apparently empty slot is free for all purposes.

Use the client `rules-snapshot --output /private/path/device-rules.json` to record the raw response from each rule set; the output file must not already exist. The client checks that State, Once, StopOnError, Rules and a matching UTF-8 byte Length are present, as in 15.1.0; incompatible responses are refused. This is not a full configuration backup; it cannot reverse other device settings, queued events, external effects, timers or variables. Verify your backup's completeness and file permissions. A snapshot can include secrets. Unix creation mode is 0600; on Windows verify inherited ACLs, which Python's mode argument does not guarantee.

## Design and transfer

One set holds concatenated clauses `ON <trigger> DO <command> ENDON` or `BREAK`. Required spaces matter. `BREAK` prevents later clauses in the same set from running after a match. `Rule1`, `Rule2`, `Rule3` are independent; `Rule1 1` enables, `Rule1 0` disables, `Rule1 4/5` control one-shot behavior. Consult command documentation for other modes. Enabling or editing an already enabled set can cause real actions as soon as an event arrives.

- Explain triggers, actions, state, timing, edge cases, recursion and side effects. Preserve unrelated clauses and the original modes. Check for conflicts with existing timers, variable names, GPIOs, topic overrides, teleperiod, initialization and other rules. Avoid automatic changes to those settings.
- `Backlog` separates actions using semicolons. Do not wrap a whole rule definition in an outer backlog or split it on semicolons: they may belong to the rule or its `IF`. Nested `IF` and ordering have firmware-specific constraints; read the documentation for the exact build.
- `%value%`, `%varN%` etc. are expanded by the rules engine; substitutions in a backlog may reflect values before its actions execute. `Var` is volatile and `Mem` persists. Avoid repeated writes and loops, especially involving persistent memory.
- `RuleN <definition>` replaces the set; `RuleN + <clause>` appends; `RuleN "` clears it. Append is not idempotent and can duplicate clauses. Do not assume deleting one clause is possible without rewriting the set.
- On 15.1 the web command handler checks the decoded command against `MQTT_MAX_PACKET_SIZE`; compression and available storage depend on build and device settings. Do not guess a universal length limit or silently truncate. If a command cannot fit, devise a documented, explicitly reviewed staged approach using complete clauses and read back each step; never split at arbitrary semicolons. Staging an active set may trigger partial behavior. Stop on uncertainty.
- Use a private UTF-8 one-line command file or stdin for shell-sensitive content. Treat rule files as sensitive and remove temporary files only when authorized. Never put secrets into command arguments.

## Verify and recover

Read `RuleN` after every write. Compare its entire returned `Rules` text with the intended final text, accounting only for device transformations actually verified; inspect State, Once, StopOnError, free space and any error. Displayed output is redacted on a best-effort basis and is therefore not guaranteed to be an exact copy; for an exact comparison use a fresh, private raw snapshot without printing or sharing secrets. HTTP 200, empty JSON or a successful write response does not prove correctness. A write may change a live set before verification.

Functional testing requires a safe, explicitly approved plan; even `Event` may switch equipment, publish externally or cause a chain of rules. Observe logs without changing log levels by default. Validate intended behavior, boundary cases and absence of unexpected effects. If changes are uncertain or verification fails, stop and report exactly what is known; do not blindly retry or auto-restore.

Recovery requires reviewing the snapshot and current device state. Restoring is itself a potentially unsafe change: obtain appropriate approval, restore the rule text and relevant modes in a safe order, then read back and verify. Do not claim that a rollback undoes actions already performed.

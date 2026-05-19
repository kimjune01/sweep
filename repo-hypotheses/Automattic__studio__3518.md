# Automattic/studio#3518 — "Could not determine the version of the SQLite integration plugin" on pull

**Issue:** Database pull from WP.com fails on Studio 1.9.0 with:
> Database import failed: Error: Could not determine the version of the SQLite integration plugin.

**Source of error string:** `Automattic/wp-cli-sqlite-command/src/SQLiteDatabaseIntegrationLoader.php::get_plugin_version()` (commit c31e09e9, also v1.1.7 latest, which Studio bundles via `download-wp-server-files.ts`).

## H₀ — error is raised by wp-cli-sqlite-command's `get_plugin_version()` returning false

`get_plugin_version()` has four false-return gates:

| Gate | Code | Returns false when |
|------|------|--------------------|
| G1   | `file_exists(ABSPATH.'/wp-content/db.php')` | db.php missing |
| G2   | `preg_match('/define\\( \\'SQLITE_DB_DROPIN_VERSION\\', \\'([0-9.]+)\\' \\)/', db.php)` | db.php exists but isn't the SQLite dropin (no matching define) |
| G3   | `get_plugin_directory()` finds `mu-plugins/sqlite-database-integration` or `plugins/sqlite-database-integration` | plugin dir absent |
| G4   | `preg_match('/^Stable tag:\\s*?(.+)$/m', readme.txt, $m)` | readme.txt missing or has no `Stable tag:` line |

Then in `load_plugin()`: `if ( ! $sqlite_plugin_version )` raises `WP_CLI::error( 'Could not determine the version of the SQLite integration plugin.' )`.

**Trajectory:** deduction (reading source). Confidence: 99%. The string is unique to that file.

## State of the bundled artifacts (master HEAD)

- `apps/studio/src/constants.ts`: `SQLITE_DATABASE_INTEGRATION_VERSION = 'v3.0.0-rc.3'` (downloaded from WordPress/sqlite-database-integration release).
- Bundled v3.0.0-rc.3 `db.copy` contains `define( 'SQLITE_DB_DROPIN_VERSION', '1.8.0' );` → satisfies G2 regex.
- Bundled v3.0.0-rc.3 `readme.txt` contains `Stable tag:        3.0.0-rc.3` → satisfies G4 regex (captures `3.0.0-rc.3`).
- `version_compare('3.0.0-rc.3', '2.1.11', '<')` → false (PHP treats `3.0.0` as the leading sort key) → gate at v1.1.7 loader line 76 passes.

So the bundled artifacts themselves satisfy every gate when intact. The bug requires one of the artifacts to be **mutated or missing in the user's site state at the moment `wp sqlite import` runs**.

## H₁ — backup's `wpContentFiles` overwrites Studio's bundled `db.php` mid-import

`apps/cli/lib/import-export/import/importers/importer.ts` (BaseBackupImporter):

1. `moveExistingWpContentToTrash` (L162) preserves `db.php`, `mu-plugins/sqlite-database-integration/**`, etc.
2. `importWpConfig`
3. **`importWpContent`** (L201) unconditionally copies every file in `this.backup.wpContentFiles` over the destination — no exclusion list for `db.php` or `mu-plugins/sqlite-database-integration/**`. If the WP.com Atomic backup contains a `wp-content/db.php` (a non-SQLite dropin — e.g., persistence/cache layer), it replaces Studio's bundled one. G2 then fails.
4. `moveExistingDatabaseToTrash` + `createEmptyDatabase`
5. **`importDatabase`** (L36) — runs `wp sqlite import` → loader fails at G2.
6. (only in `pull.ts` finally block, L218) `keepSqliteIntegrationUpdated` reinstalls — but too late; import has already errored.

**Perturbation to confirm (frontier):** stage a backup tar.gz with `wp-content/db.php` containing arbitrary non-SQLite-dropin content, run BaseBackupImporter against a fresh Studio site, observe that post-`importWpContent` the bundled db.php is gone.

**Trajectory if confirmed:** divergent. Confidence (abduction): 70%. Hinges on whether WP.com Atomic backups actually include a `db.php`.

## H₂ — backup overwrites `mu-plugins/sqlite-database-integration/` with stale files

Same mechanism as H₁ but at G3/G4. If the user had previously *pushed* a Studio site (which would upload `mu-plugins/sqlite-database-integration/` to WP.com), the WP.com side now has an OLD Studio-shipped version of the plugin (e.g., 2.1.x). On subsequent pull, `importWpContent` copies those files over Studio's bundled v3.0.0-rc.3. The folder still exists (G3 ok) but the `readme.txt` is older — still has a `Stable tag:` → G4 passes — but the version-compare in `load_plugin()` may fail if Stable tag < 2.1.11.

If Stable tag is missing or empty (e.g., a partial overwrite, or the version line was stripped), G4 fails directly.

**Trajectory:** abduction. Confidence: 40%. Maintainer's diagnostic question to the reporter ("check `wp-content/mu-plugins/sqlite-database-integration/readme.txt`") suggests they suspect this branch.

## H₃ — fresh-site path: bundled artifacts never installed

User reports "I've tried with a fresh local site". On site create, `apps/cli/commands/site/create.ts:233` calls `keepSqliteIntegrationUpdated`. That calls `installSqliteIntegration` only if `needsSqliteSetup` returns true. `needsSqliteSetup` returns `hasDbPhp || !hasWpConfig`. On a brand-new site, `hasWpConfig` is false → true → installs. So fresh sites *do* get the bundled SQLite. This makes H₃ unlikely as a fresh-site failure mode, **unless** the download step (`scripts/download-wp-server-files.ts`) silently fetched a corrupt zip, or the v3.0.0-rc.3 readme.txt got malformed.

**Killable cheaply:** reporter on Mac Silicon; have them check `wp-content/mu-plugins/sqlite-database-integration/readme.txt` on a freshly created site BEFORE any pull. If readme.txt is intact and shows `Stable tag: 3.0.0-rc.3`, H₃ dies.

**Trajectory:** abduction. Confidence: 15%.

## H₄ — db.php overwrite happens earlier, via `importWpConfig`

`importWpConfig` (L190) copies `backup.wpConfig` to `wp-config.php`. It does NOT touch db.php. So this is not the vector. H₄ killed by deduction (read the code).

## Causal chain (current best guess)

`pull with database option` → `BaseBackupImporter.import` → `importWpContent` copies backup wp-content files → (if backup includes `wp-content/db.php` or stale `mu-plugins/sqlite-database-integration/**`) → Studio's bundled SQLite dropin/plugin is replaced → `importDatabase` invokes `wp sqlite import` → `wp-cli-sqlite-command` loader's `get_plugin_version()` fails at G2 or G4 → error surfaces.

## Frontier edges

1. **What does a WP.com Atomic backup actually contain at `wp-content/db.php`?** Need a real backup tar.gz or the WP.com backup-emit spec. Without this, H₁ is theory.
2. **Reporter's `mu-plugins/sqlite-database-integration/readme.txt` contents at the failure point.** Maintainer has already asked this in comment thread (wojtekn, 2026-05-18). Wait for user.
3. **Idempotency of fresh-site path.** Have the reporter verify that on a fresh site created by 1.9.0, the bundled plugin is intact pre-pull.

## Fix shape (provisional — DO NOT SHIP UNTIL FRONTIER EDGE 1 OR 2 IS CLASSIFIED)

If H₁ or H₂ confirms, the minimal fix is one of:

**Option A** (defensive — exclude SQLite paths from backup copy): in `importWpContent`, skip any file whose relativePath matches `db.php` or `mu-plugins/sqlite-database-integration/**`. Symmetric with `moveExistingWpContentToTrash`'s keep list.

**Option B** (idempotent — reinstall SQLite after content copy): insert `await keepSqliteIntegrationUpdated( site.path )` (or a force-install variant) between `importWpContent` and `importDatabase` in `BaseBackupImporter.import`. This is closer to the existing pattern; the post-pull `keepSqliteIntegrationUpdated` in `pull.ts` finally block already exists, just at the wrong point in the sequence for the failing path.

Option B is closer to existing code conventions. Test would assert call order: `installSqliteIntegration` called between `importWpContent` and the first `runWpCliCommand` invocation for `['sqlite', 'import', ...]`. Fail-on-master would mock `getMuPluginsTrash` / construct a backup with a `wp-content/db.php` file, run BaseBackupImporter, verify final db.php has SQLITE_DB_DROPIN_VERSION define.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| Error string originates in wp-cli-sqlite-command's loader | Deduction | 99% |
| Bundled v3.0.0-rc.3 artifacts satisfy all four gates when intact | Induction (downloaded and inspected) | 95% |
| `importWpContent` copies all backup files unconditionally over preserved Studio files | Deduction (read importer.ts) | 95% |
| WP.com Atomic backup contains a `wp-content/db.php` that fails G2 | Abduction | 50% |
| User's site has a stale `mu-plugins/sqlite-database-integration/` from prior push | Abduction | 35% |
| Option B fix shape correctly addresses H₁ and H₂ | Deduction | 80% (conditional on H₁/H₂ confirming) |

## Halt

Frontier edges 1 and 2 require data we don't have:
- Maintainer (wojtekn) is actively driving a diagnostic question to the reporter (posted 2026-05-18, ~30h before this investigation). The reporter hasn't responded yet.
- Shipping a speculative fix now would race the maintainer's own diagnostic loop and risk fixing the wrong gate.

**Action:** record this graph; do not open a PR. Re-enter when reporter responds, or when the maintainer confirms a specific gate (G2 vs G4) is the trigger.

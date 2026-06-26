# GUI Contract — Native macOS Profile Editor (profile-use)

A single authoritative spec for a SwiftUI app (main window editor + menu-bar quick-copy) that reads/writes the profile-use JSON natively, schema-driven, with standard privacy gating. This contract is derived from `references/profile-schema.json`, `references/profile-template.json`, `scripts/profile_use.py`, `SKILL.md`, `references/sync-model.md`, and `README.md`.

**Authority rule for divergence:** trust `profile-template.json` for the inner leaves/defaults of `payment`/`bank`/`government_id`/`tax`/`preferences` and the `documents` map; trust `profile-schema.json` for explicit per-field sensitivity tags. The merged model below is the rendering target.

---

## 1. Data model

### 1.1 Codable shape & invariants

- Root is a JSON object with `additionalProperties: true`. **The Codable model MUST preserve unknown keys round-trip** (catch-all dictionary), never dropping them on save.
- Every leaf is a JSON **string** except three booleans: `payment.card.billing_address_same_as_profile` (default `true`), `preferences.marketing_opt_in` (default `false`), plus any boolean values that appear inside `documents`.
- `documents` is a **free-form keyed map** (`{}` in the template) — render as a dynamic attachment list, not fixed fields.
- JSON serialization on write: `indent = 2`, `ensure_ascii = false` (preserve CJK), trailing newline, UTF-8.
- Empty values (`""`, `null`, `[]`, `{}`) are valid and pass through unchanged; never masked, and skipped by "filled" logic.

### 1.2 Sensitivity is the renderer driver

Three tiers drive both display redaction and the unlock/consent gate:

- **low** — shown plainly, editable inline.
- **medium** — masked in summaries but easy one-tap reveal; usable for autofill.
- **high** — masked by default, Touch ID gate per reveal/edit, never auto-copied, excluded from bulk dumps.

**Section-level sensitivity cascades:** `payment`, `bank`, `government_id`, `tax` carry the HIGH tag on the parent object; **every descendant leaf inherits HIGH** even though the leaf itself has no tag. Matching is **segment-aware prefix**: a path matches a sensitivity prefix when `path == prefix` OR `path.startsWith(prefix + ".")`. So `"tax"` must NOT match `"taxonomy"`.

### 1.3 Field model grouped by section

**Section order (schema order):** `profile_name`, `identity`, `contact`, `address` (+ `address.jp`), `payment`, `bank`, `government_id`, `tax`, `preferences`, `documents`, `notes`.

#### root scalars
| Path | Type | Sensitivity | Notes |
|---|---|---|---|
| `profile_name` | string | low | identifies/selects profile; drives multi-profile |
| `notes` | string | medium | free text |

#### identity
| Path | Type | Sensitivity |
|---|---|---|
| `identity.full_name` | string | medium |
| `identity.family_name` | string | medium |
| `identity.given_name` | string | medium |
| `identity.middle_name` | string | medium |
| `identity.preferred_name` | string | low |
| `identity.birthdate` | string (date) | **high** |
| `identity.gender` | string | **high** |

#### contact (all medium)
| Path | Type | Sensitivity |
|---|---|---|
| `contact.email` | string | medium |
| `contact.phone_country_code` | string | medium |
| `contact.phone` | string | medium |
| `contact.alternate_email` | string | medium |

#### address
| Path | Type | Sensitivity |
|---|---|---|
| `address.country` | string | medium |
| `address.region` | string | medium |
| `address.city` | string | medium |
| `address.ward_or_district` | string | medium |
| `address.line1` | string | **high** |
| `address.line2` | string | **high** |
| `address.postal_code` | string | medium |

#### address.jp (nested) — JP-form fallback
| Path | Type | Sensitivity |
|---|---|---|
| `address.jp.prefecture` (都道府県) | string | medium |
| `address.jp.city` (市区町村) | string | medium |
| `address.jp.banchi` (番地) | string | **high** |
| `address.jp.building` (建物名) | string | **high** |
| `address.jp.postal_code_hyphenated` (e.g. `100-0001`) | string | medium |

> **JP fallback rule (load-bearing for autofill):** prefer `address.jp.*` on Japanese forms; fall back to the generic `address.*` field whenever the `jp.*` value is absent/empty.

#### payment (section HIGH → all leaves high)
| Path | Type | Sensitivity | Notes |
|---|---|---|---|
| `payment.card.holder_name` | string | high | |
| `payment.card.number` | string | high | most sensitive |
| `payment.card.expiry_month` | string | high | |
| `payment.card.expiry_year` | string | high | |
| `payment.card.cvv` | string | high | most sensitive |
| `payment.card.billing_address_same_as_profile` | boolean | high | default `true` → reuse `address.*` for billing |

#### bank (top-level, section HIGH → all leaves high)
`bank.country`, `bank.bank_name`, `bank.branch_name`, `bank.account_type`, `bank.account_number`, `bank.routing_number`, `bank.iban`, `bank.swift`, `bank.holder_name` — all string, all **high**.

#### government_id (section HIGH → all high)
`government_id.country`, `government_id.type` (passport / driver's license / residence card discriminator), `government_id.number`, `government_id.expiry` — all string, all **high**.

#### tax (section HIGH → all high)
`tax.country`, `tax.tax_id` — string, **high**.

#### preferences (section LOW)
| Path | Type | Sensitivity | Notes |
|---|---|---|---|
| `preferences.locale` | string | low | |
| `preferences.currency` | string | low | |
| `preferences.marketing_opt_in` | boolean | low | default `false` |

#### documents (HIGH, dynamic)
`documents` — free-form `{ <docKey>: {file, label, source, added, sha256} }` map. Treat as **high**, render as attachment list (§4).

### 1.4 Schema-driven renderer

Build the form from a static field-descriptor table `[ {path, section, swiftType, sensitivity} ]` (the rows above), NOT hand-coded views. For each descriptor: render a control by `swiftType` (TextField / DatePicker for `string(date)` / Toggle for boolean), wrap it in a redaction/reveal cell driven by `sensitivity`, and group by `section` headers in schema order. The catch-all unknown-keys dictionary is rendered (read-only is acceptable) so round-trip preservation is visible and never silently dropped.

---

## 2. Storage

### 2.1 Path resolution (the GUI MUST implement exactly, first match wins)

1. **Env override:** `$PROFILE_USE_DIR`, then legacy `$PERSONAL_AUTOFILL_DIR` (expand `~`). Env vars are for temporary automation only; the GUI reads them if set but should not depend on them.
2. **iCloud Drive** (if the iCloud root `~/Library/Mobile Documents/com~apple~CloudDocs` exists):
   `~/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/profile-use`
   — but if that new dir is absent and the legacy `~/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/personal-autofill` exists, use the legacy one.
3. **Local fallback** (iCloud root absent): `~/.config/profile-use`
   — same legacy fallback to `~/.config/personal-autofill` when the new dir is absent and legacy present.

iCloud dir is **created on first write** ("Agent Profiles" need not pre-exist).

### 2.2 File layout & multi-profile

- Profile file: `<dir>/<profile>.profile.json` (default profile = `personal`).
- **Profile name validation:** regex `^[A-Za-z0-9][A-Za-z0-9_-]*$` — reject path separators/traversal (the name becomes both filename and attachments subdir). Reject invalid names in the UI before any I/O.
- Multi-profile = pick the active profile in the UI (`personal` default, plus `work`/`family`/`jp`/etc.). Never cross-contaminate between profiles.

### 2.3 Atomic write + permissions (mandatory)

- `mkdir -p` parents; `chmod 0700` on the parent dir (best-effort).
- Serialize → write to temp `.<name>.tmp` opened with `O_CREAT|O_TRUNC` at mode **0600** (no create-then-chmod window), then atomic `rename`/`os.replace` over the target. Unlink temp on error.
- Resulting profile JSON is mode **600**. In Swift: open via `open(path, O_CREAT|O_TRUNC|O_WRONLY, 0o600)` (or `Data.write` then immediately `FileManager.setAttributes [.posixPermissions: 0o600]`, but prefer the no-window approach), then `FileManager` rename.

### 2.4 Recommendation: resolve natively, shell out only as escape hatch

**Replicate path resolution natively** (it is small, deterministic, pure file logic — §2.1) so the editor and menu-bar app have zero subprocess latency on every read. **Do NOT depend on `profile_use.py path/doctor` for the normal resolve path.** Keep `doctor` as a one-shot **diagnostic escape hatch** the GUI can shell out to (and display its JSON) when a profile unexpectedly lands in `~/.config` or the user clicks "Diagnose storage" — `doctor` reports env vars, iCloud root + exists, iCloud profile path + exists, local fallback + exists, and resolved default path, with no secrets. This keeps the GUI authoritative for hot paths while reusing the helper's exact diagnostic semantics for troubleshooting.

> Never commit plaintext profiles to any repo (`.gitignore` blocks `*.profile.json`). Only encrypted backups (`.age`/sops) and schema/templates belong in Git. The GUI must not write profile contents anywhere outside the resolved profile dir.

---

## 3. Privacy / redaction rules

### 3.1 Display defaults — redaction is ON

The editor and all summaries/lists/confirmations show **redacted** values by default (mirrors `show`/`get`). Raw is shown only by a deliberate, user-initiated reveal — gated per sensitivity. Raw high-sensitivity values must NEVER appear in any "final summary" surface.

### 3.2 Exact masking functions (match `redact_value` precisely)

Apply by path, recursively over dicts/lists. `""`/`null`/bool/int/float pass through unchanged (only strings get masked). Evaluate in this order:

1. **HIGH-sensitivity prefix** (`is_high_sensitivity`, segment-aware match against the prefix set): `mask_tail(text, 4)` — keep last 4 chars, rest `*`; whole string `*` if `len ≤ 4`.
   **HIGH prefixes:** `payment`, `bank`, `government_id`, `tax`, `identity.birthdate`, `identity.gender`, `address.line1`, `address.line2`, `address.jp.banchi`, `address.jp.building`, `documents`.
2. **NAME_FIELDS** (`identity.full_name`, `family_name`, `given_name`, `middle_name`, `name_kana`): `redact_name` — keep first letter of each whitespace token, rest `*`; single-char tokens unchanged.
3. **path contains `email`**: `redact_email` → `x***@domain` (first char + `***@` + domain; if no `@` → `mask_tail(text, 2)`; empty localpart → `***@domain`).
4. **path ends `phone_country_code`**: shown as-is (dialing code like `+81` is not sensitive).
5. **path contains `phone` or `postal_code`**: `mask_tail(text, 2)`.
6. **`address.line1`/`address.line2` OR path == `notes`**: `mask_tail(text, 4)`. (line1/line2 already hit the HIGH branch first; notes lands here.)
7. **else**: shown as-is (low passthrough).

### 3.3 Per-tier UI behavior

| Tier | Display | Reveal | Edit | Copy / fill |
|---|---|---|---|---|
| **low** | shown plainly | n/a | inline, no gate | freely copyable |
| **medium** | masked in summaries, easy one-tap reveal (no biometric) | one tap | inline after reveal | usable for autofill; raw fetched at fill time |
| **high** | masked, never auto-revealed | **Touch ID per reveal** | **Touch ID per edit** | **never auto-copied**; excluded from bulk dump; request by name + Touch ID per fill |

- **Touch ID gate is per-action** (per reveal, per edit, per fill) — not a session-wide unlock. Use `LAContext` (`LAPolicy.deviceOwnerAuthenticationWithBiometrics`) for each high-sensitivity reveal/edit/copy.
- High-sensitivity and credential values are **never auto-included** in any bulk operation; the GUI must request each one by name (mirrors `values --include-sensitive` opt-in: explicitly naming a field returns it raw; the no-field dump excludes high-sensitivity unless opted in).
- **Never auto-submit** any registration/KYC/checkout/banking/login form — present a redacted summary, wait for explicit approval.
- **Never invent missing data** — prompt the user or leave blank; never auto-generate.
- **Ask before persisting** any newly captured field; new high-sensitivity / `payment`/`bank`/`government_id`/`tax`/`birthdate` paths stay confirmation-gated even under a broad "record stuff" consent. Never save one-time codes, CAPTCHA text, session tokens, or site passwords.

### 3.4 Menu-bar quick-copy flow

The menu-bar app lists copyable values (by label) from the active profile. Flow:

1. User clicks a value entry in the menu-bar dropdown.
2. **If low/medium:** copy raw to clipboard immediately (medium may show a brief reveal preview).
3. **If high:** trigger **Touch ID** (`LAContext`) → on success, copy the chosen raw value to the clipboard. There is **no auto-copy** of high-sensitivity values without that per-action biometric step.
4. The menu never displays raw high-sensitivity text in the dropdown — labels/masked tokens only until the user picks one and authenticates.
5. Recommended: schedule a clipboard auto-clear after a short interval for high-sensitivity copies (defense-in-depth; not required by the helper but consistent with "never leak").

---

## 4. Documents

### 4.1 Storage model

- Attachments dir: `<profile-dir>/attachments/<profile>/` — **dir mode 0700**, each file **mode 0600**. Stored next to the profile so it syncs via iCloud and never enters Git.
- Stored filename = `<docKey>` + source file's suffix **lowercased** (e.g. `residence_card.jpg`).
- **Doc key validation:** `^[a-z0-9][a-z0-9_.-]*$` (lowercase). Reject otherwise.
- Metadata recorded under `documents.<docKey>` in the profile JSON: `{ file, label, source, added (ISO date), sha256 }`. `documents` is HIGH (masked) in summaries.
- **`safe_attachment_path` defense:** reject any stored filename containing `/`, `\`, `.` (bare), `..`, or anything resolving outside `attachments/<profile>/` — defends against a poisoned `documents.*.file` value. The GUI must replicate this check before resolving/opening any attachment path.

### 4.2 GUI list / add / remove (mirrors `attach` / `attachments` / `detach`)

- **List:** for each `documents.<key>`, show resolved absolute path, exists flag, `size_bytes`, and `label`/`source`/`added`. Flag `unsafe_filename` for entries failing the safe-path check. Also surface **orphan files** present in the attachments dir but not tracked in metadata.
- **Add:** copy the selected file into the attachments dir as `<docKey><lowercased suffix>`; compute and record `sha256`; set `added` (ISO date). Refuse to overwrite an existing doc key unless the user confirms "replace"; on replace, unlink the previous file if its name differs. Optional "move" mode deletes the source after copy (clean up `/tmp`/`Downloads` — never leave originals there). Set dir 0700 / file 0600.
- **Remove (`detach`):** delete `documents.<key>` from the profile and unlink the file if present; only write the profile if metadata existed. Report `removed_file`.
- **Upload to a website:** hand the upload widget the file path (mirrors `attachment-path`) — **each individual upload requires its own explicit confirmation**, even if text autofill was already approved. Never re-screenshot or copy the image elsewhere. Don't attach one-time docs (CAPTCHAs, QR codes, temporary passes).

---

## 5. CLIBridge surface

The GUI is **native file I/O first**. Everything in §1–§4 (resolve path, read/parse/serialize, atomic 600 write, redaction, attachments) is implemented natively in Swift — no subprocess on hot paths. Shell out to `scripts/profile_use.py` only for the narrow set below.

### Native (no shell-out)
- Path resolution (§2.1), profile read/parse, schema-driven render, atomic 0600 write (§2.3), unknown-key preservation.
- All redaction/masking (§3.2) — reimplement the functions exactly in Swift.
- All document attach/list/detach/path + safe-path validation + sha256 (§4).
- `get`/`set`/`unset`/`values` semantics — reimplement as native model operations.

### Shell-out (CLIBridge) — keep minimal
| Operation | Helper command | Why shell out |
|---|---|---|
| Storage diagnostics | `profile_use.py doctor --profile <P>` | Authoritative env/iCloud/fallback report on demand; rare, troubleshooting only |
| (optional) Path echo | `profile_use.py path --profile <P>` | Cross-check native resolution if a discrepancy is suspected; not on hot path |
| **Login credentials** | `profile_use.py login [--domain/--name/--user] [--reveal] [--deep]` | rbw/Bitwarden read-through; the GUI should NOT reimplement vault access |
| Vault status | `profile_use.py vault-status` | reports `{rbw_installed, rbw_path, base_url, email(masked), unlocked}` |
| Vault setup | `profile_use.py vault-setup [...]` | install/config rbw |

### Credentials rule (hard)
- Login passwords/credentials **NEVER** live in the profile JSON, memory, logs, temp files, or chat — they are read **live from the vault each time** via `login` and re-read every time.
- The GUI must **never** ask for, capture, store, or echo the rbw master password, and must **never** run `rbw login`/`unlock` itself — it surfaces the command for the human. Check `vault-status.unlocked` before attempting a domain lookup; if locked, show the fix command ("Run: `rbw unlock`").
- `login` default output is redacted: password fixed-width `********` (never length-revealing), username email-aware masked, totp shown only as `present`, URIs shown raw. `--reveal` only at the instant of filling. Multiple matches → list masked candidates and fetch nothing until disambiguated by `--name`/`--user`.

---

Reference files (absolute paths):
- `/Users/leo/github.com/profile-use/references/profile-schema.json` — authoritative types + per-field sensitivity
- `/Users/leo/github.com/profile-use/references/profile-template.json` — authoritative inner leaves + defaults + `documents` map
- `/Users/leo/github.com/profile-use/scripts/profile_use.py` — authoritative redaction, path resolution, atomic-write, attachment, and rbw read-through logic
- `/Users/leo/github.com/profile-use/SKILL.md`, `/Users/leo/github.com/profile-use/references/sync-model.md`, `/Users/leo/github.com/profile-use/README.md` — storage/sync model + privacy hard rules

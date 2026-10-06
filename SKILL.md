---
name: profile-use
description: Safely use a user's private local personal profile to help fill registration, signup, checkout, banking, KYC, and onboarding forms. Use when the user asks to enter or reuse identity details such as name, address, phone, postal code, email, birthdate, payment card, bank account, tax ID, or other personal data. Also use whenever a task hits a login wall: sign in proactively with the Bitwarden vault (bitwarden-use) and finish 2FA with SMS codes (message-use) or email codes and magic links (mail-use) instead of asking the user to log in. Prioritize privacy, redaction, consent before submission, and local/iCloud/encrypted profile sources rather than storing personal data in chat or Git. Also use leak-scan before committing to any repo that might echo personal data. Not for infra/NAS/VPN notes or "how did we do X" history — that is memory-use.
---

# Profile Use

Use a private profile as the source of truth for repetitive registration and checkout fields. The skill helps map form labels to profile fields, fill only what is needed, and keep sensitive values out of chat, logs, screenshots, repos, and PRs.

## Privacy Rules

1. Never invent personal data. If a field is missing, ask the user or leave it blank.
2. Do not store real personal data in the skill repo, memory, issue trackers, PRs, screenshots, or final responses.
3. Use redacted summaries by default. Reveal full values only when the user explicitly asks and the current task requires it.
4. Treat payment cards, bank accounts, government IDs, tax IDs, passwords, security answers, and medical fields as high sensitivity. Ask for explicit confirmation before entering or revealing them.
5. Do not submit a registration, KYC, checkout, banking, or payment form until the user explicitly approves the final submit action. Signing in to the user's own existing account is the exception: see *Logging In*.
6. If browser automation is used, verify the real domain and purpose before filling. Stop on suspicious, unrelated, or typosquatted domains.

## Profile Source

Prefer the helper script:

```bash
python3 scripts/profile_use.py path
python3 scripts/profile_use.py doctor
python3 scripts/profile_use.py init --profile personal
python3 scripts/profile_use.py show --profile personal
python3 scripts/profile_use.py values --profile personal
python3 scripts/profile_use.py values --profile personal contact.email address.postal_code
python3 scripts/profile_use.py get --profile personal contact.email address.postal_code
python3 scripts/profile_use.py set --profile personal address.postal_code "1000001"
python3 scripts/profile_use.py list-fields --profile personal --filled
```

### Redacted vs. raw: pick the right command

This is the most important rule for autofill. Two output modes exist and they are not interchangeable:

- **`values`** returns RAW values. Use it for every value you actually type into a form. With no fields it dumps all filled low/medium fields as a flat `{dotpath: value}` map ready to map onto form labels; it excludes high-sensitivity fields unless you name them or pass `--include-sensitive`.
- **`show` / `get`** return REDACTED values by default (names, email, phone, address lines, card, bank, IDs, notes are masked). Use these only to orient or to report back to the user. Pass `--reveal` to unmask.

NEVER type a redacted/masked value into a form. `get contact.email` returns `t***@example.com`; filling that breaks the registration. To fill, use `values contact.email` (or `get --reveal`). When in doubt for filling: use `values`.

Default location order:

1. `$PROFILE_USE_DIR` (legacy `$PERSONAL_AUTOFILL_DIR` is still honored)
2. `$HOME/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/profile-use`
3. `$HOME/.config/profile-use`

A pre-rename `personal-autofill` directory that still holds data is used as a fallback when the `profile-use` directory does not exist yet.

The iCloud rule checks the iCloud Drive root (`com~apple~CloudDocs`) and creates `Agent Profiles/profile-use` on first write. Use `doctor` when a profile unexpectedly lands in `.config`.

Use `references/profile-template.json` for the editable shape. Use `references/profile-schema.json` for field names and sensitivity hints.

## Growing The Profile

Expect the profile to grow over time as real registrations reveal new fields. When a form asks for information that is not already in the profile:

1. Ask the user for the value only if it is required for the current registration.
2. Decide whether it is reusable. Save stable values such as alternate emails, shipping addresses, invoice names, furigana, company details, and country-specific address variants. Do not save one-time codes, session tokens, CAPTCHA text, temporary invitation links, or site passwords.
3. Ask before writing high-sensitivity or newly invented field paths.
4. Add the field with `set`:

```bash
python3 scripts/profile_use.py set --profile personal identity.name_kana "..."
python3 scripts/profile_use.py set --profile personal address.jp.prefecture "..."
python3 scripts/profile_use.py set --profile personal preferences.newsletter_opt_in false --json
```

5. Confirm with redacted reads:

```bash
python3 scripts/profile_use.py get --profile personal identity.name_kana address.jp.prefecture
```

Use flexible nested paths when a country, site, or tenant needs a special variant. Examples: `address.jp.*`, `address.us.*`, `contact.work_email`, `invoice.jp.qualified_invoice_name`.

### Proactive Capture (offer to record, don't wait for a form)

Profile growth is not limited to autofill. During **any** task — answering a tax question, reading a chat, helping with onboarding paperwork — durable personal facts surface that the user will likely need again. When that happens, **proactively offer to record them**, then write only after the user agrees:

1. Notice the fact is **stable and reusable**, not one-time. Good: family members' birthdates / relationships, dependent and tax-residency status, employer / salary structure, an HR- or authority-confirmed requirement (what document is needed, who handles it), a recurring address or invoice variant. Skip: one-time codes, transient amounts, session/case context that won't recur.
2. **Ask before writing.** Say what you'd save and the dotpath (e.g. "记进 `family.father.birthdate` / `tax.jp.dependents.*`?"). Get a yes first; never silently persist. The exception is when the user already said "record this" / "记一下" — then write and report.
3. Pick a sensible path under an existing section before inventing a new top-level one; flexible nested paths are fine (`family.*`, `tax.jp.dependents.*`). Treat new high-sensitivity paths and any `payment`/`bank`/`government_id`/`tax`/birthdate value as confirmation-gated even when the user broadly agreed to "record stuff".
4. After writing, confirm with a redacted `list-fields --filled` / `get`, and report the dotpath — not the raw value — back to the user.

Keep all other rules in force: redaction by default, nothing high-sensitivity revealed in the final response, and the profile JSON stays the store of record (not chat, memory, or Git).

## Fill Workflow

1. Identify the form's site, purpose, and profile to use. Default to `personal` unless the user names another profile such as `work`, `family`, or `jp`.
2. Inspect the form labels and required fields. Build a mapping from labels to profile paths; do not rely only on placeholder text.
3. Orient with redacted `show` to see the shape, then read the exact values you will type with `values` (raw). Use `values` with no fields to get a flat map of all filled low/medium fields at once.
4. Fill low-sensitivity fields directly when the user asked for autofill, using the raw `values` output. Examples: name, email, phone, postal code, `address.country` / `address.region` / `address.city`.
5. For high-sensitivity fields (`payment`, `bank`, `government_id`, `tax`, birthdate, gender, and the street-address lines `address.line1` / `address.line2`), show a redacted summary and ask for confirmation before filling; fetch the raw value with an explicit `values address.line1` (or `values payment.card.number`) only at the moment of filling. These are excluded from the no-field `values` dump, so you must name them.
6. Before submission, summarize the fields that were filled using redacted `show`/`get` values and wait for an explicit submit approval.

## Field Mapping Hints

- `identity.full_name`: full legal name or display name, depending on the form.
- `identity.family_name`, `identity.given_name`: split-name fields.
- `contact.email`, `contact.phone`, `contact.phone_country_code`: email and telephone fields.
- `address.country`, `address.region`, `address.city`, `address.postal_code`: address fields (low sensitivity). `address.line1`, `address.line2`: the precise street address — high sensitivity, masked in `show` and excluded from the no-field `values` dump.
- `payment.card.*`: card fields; always high sensitivity.
- `bank.*`: bank transfer or withdrawal fields; always high sensitivity.
- `government_id.*`, `tax.*`: identity verification fields; always high sensitivity.
- `preferences.*`: marketing opt-in, locale, newsletter, and delivery preferences.
- `invoice.*`: billing name, tax invoice name, receipt name, or business invoice details.
- `site_overrides.<domain>.*`: a value required only by one service; use this sparingly.

If a site has country-specific formatting rules, preserve the profile value unless the form rejects it. Normalize only after checking the visible validation message.

### Output formats for `values`

Two flags on `values`, for the two conversions agents kept doing by hand at
fill time:

- `--phone-format domestic|e164` — `contact.phone` as the trunk-prefixed
  national number (`07012345678`) or E.164 (`+817012345678`). Only applies when
  `contact.phone_country_code` is on file; without it there is no honest way to
  tell `+81 70` from a national `070`, so the value is returned as stored.
- `--format jp-fullwidth` — ASCII digits, letters and hyphens in every returned
  string as full-width (`100-0001` → `１００－０００１`, `1番2-3号` →
  `１番２－３号`) for Japanese forms that reject half-width input. Kana
  and kanji are untouched.

```bash
python3 scripts/profile_use.py values contact.phone --phone-format domestic
python3 scripts/profile_use.py values address.jp.kana_remainder --format jp-fullwidth
```

### Conventional paths for recurring cases

The schema is free-form nested paths, so any of these can be stored today without
a code change. Use these exact paths anyway. The failure mode is not "the field
cannot be stored" — it is that each agent invents its own path (`payment.hk_bank`
one week, `bank.hk` the next), and the next agent cannot find what the last one
saved. Converging matters more than the names being perfect.

**Names as printed on an ID.** Residence cards, passports and driver's licences
print a romanised name whose order may not match `identity.family_name` /
`identity.given_name`. Japanese forms routinely want that exact string in the
漢字 slot plus a separate kana line.

- `identity.romaji.family_name`, `identity.romaji.given_name`
- `identity.name_on_id`: the name exactly as printed, including its order
- `identity.kana.family_name`, `identity.kana.given_name`

**Japanese structured address.** Forms auto-fill 都道府県/市区町村/町域 from the
郵便番号 and then want only the remainder, "as written on the ID", in full-width
digits — which cannot be re-derived reliably from `address.line1` / `line2`.

- `address.jp.{prefecture,city,town,chome,banchi,go,building,room}`
- `address.jp.postal_code_hyphenated` (`100-0001`)
- `address.jp.kana_remainder`

**Document metadata.** eKYC flows reject cards by issue date and need the card
number for the IC read, so this saves reopening the image every time. All three
are high sensitivity.

- `documents.<doc>.{number,issued_on,expires_on}` (ISO dates)
- `documents.<doc>.proves`: list of what the document evidences, e.g.
  `[name]` for 在留カード表面 and `[address]` for 裏面. Lets an agent pick the
  right file for "one document proving name, one proving address" instead of
  guessing from the label.

**Bank and payout accounts.** Use an array so multiple accounts coexist; always
high sensitivity.

- `bank.accounts[].{bank_name,account_name,account_number,branch_code,swift,clearing_code,currency,country,label}`

Prefer `bank.*` over a new top-level section — the redaction rules and the
confirmation gate already key off that prefix.

## Original Document Images (Attachments)

Some forms need the original image, not extracted text: residence card photos for KYC, bank card photos for payroll, My Number card scans. Keep these originals next to the profile so they sync with it and survive temp-file cleanup:

```bash
python3 scripts/profile_use.py attach /tmp/dl/img1.jpg --doc residence_card_front --label "在留カード 表面" --source "lark chat 2026-01-01" --move
python3 scripts/profile_use.py attachments --profile personal
python3 scripts/profile_use.py attachment-path --doc residence_card_front
python3 scripts/profile_use.py detach --doc residence_card_front
```

Files land in `<profile-dir>/attachments/<profile>/<doc>.<ext>` with mode 600; metadata (file, label, source, added date, sha256) is recorded under `documents.<doc>` in the profile JSON. This metadata is treated as high sensitivity — masked in `show`/`get` and excluded from the no-field `values` dump — because `label`/`source` often carry context (counterparty names, dates) you don't want in a redacted summary.

Conventional doc keys: `residence_card_front`, `residence_card_back`, `my_number_card_front`, `my_number_card_back`, `bank_card`, `passport_photo_page`, `health_insurance_card`, `drivers_license_front`. Free-form keys are fine (lowercase letters, digits, `_`, `-`, `.`).

Rules for originals:

1. When a document image appears in a chat download or temp directory and is worth keeping, `attach --move` it immediately, then delete any remaining temp copies. Do not leave ID images in `/tmp`, downloads, or the repo.
2. Treat every attachment as high sensitivity. Uploading an attachment to a website requires the user's explicit confirmation for that specific upload, even if autofill of text fields was already approved.
3. Use `attachment-path` to get the file path for an upload widget; never re-screenshot or copy the image elsewhere.
4. Do not attach one-time documents (CAPTCHAs, QR codes, temporary passes). Attach stable identity/payment documents only.
5. Expired or surrendered documents: `detach` them, or replace with `attach --force` when a renewed card arrives.

## Logging In (proactive)

When a task runs into a login wall (a sign-in page, an expired session, a 401, "please log in to continue"), **log in yourself and carry on**. Do not stop to ask the user to log in, and do not hand them the steps. The user stored the password in their vault, their SMS reaches this Mac, and their email is readable, all so that the agent can do this.

Account passwords do **not** live in the profile JSON. They stay in the user's vault and are read live through `bitwarden-use` (`bwu`). Second-factor codes come from `message-use` (SMS) and `mail-use` (email). Nothing from a login is ever written to the profile, memory, logs, a temp file, or chat.

### The playbook

1. **Check the domain.** The host must be the real site for the task. Stop on lookalike, typosquatted, or unrelated hosts; this is the only check that protects the password.
2. **Make sure the vault is ready.** `python3 scripts/profile_use.py vault-status`. If the CLI is missing, set it up yourself (see *Vault setup* below). A locked vault is not a reason to stop: `login` unlocks it by itself, and `vault-unlock` does it on its own. Both try the master password in the macOS keychain first, with no prompt. If that is not enrolled, they open bitwarden-use's password dialog, where the user types straight into the vault agent. Do not ask before unlocking; just run it.
3. **Sign in.**
   - In a browser: `chrome-use auth login --bwu` on the login page. The values go straight from the vault to the page and never pass through the conversation. Use `--item <name>` when the site has several accounts, and `--passkey` when the entry holds a passkey (preferred: no second factor). For multi-step forms, see the `_autotype` field in the bitwarden-use docs.
   - Anywhere else (CLI prompts, API tokens, native apps): `python3 scripts/profile_use.py login --domain <host> --reveal` reads username and password at the moment of filling.
   - Several candidates: pick by `--user` if the task makes the account obvious (e.g. the work email for a work tool); otherwise ask which account, showing the masked list.
4. **Second factor.** Work out the channel from the page text, then:

   | The site says | Do |
   |---|---|
   | Authenticator app / TOTP | `login --domain <host> --reveal` → `totp` is the current code |
   | "We texted a code to ••••78" | click "send", then `profile_use.py code --via sms --wait 120s --from <brand>` |
   | "We emailed a code" | click "send", then `profile_use.py code --via mail --wait 120s --from <brand>` |
   | Not clear which | `profile_use.py code --wait 120s --from <brand>` (asks both) |
   | "Click the link we emailed" | `mail-use email search` for the newest mail from the site, read it with `mail-use email show`, check the link's host is the site's own domain, then open it with chrome-use |
   | Push approval on a phone app, hardware key, a CAPTCHA you cannot solve | ask the user to approve it, then continue |

   `code --wait` only accepts a code that arrived after it started (with 30 s of grace for one sent just before), so it never returns the code from the last login. `--from` narrows to one sender (brand name, address, or subject fragment); use it whenever another service might be texting at the same time.
5. **Submit and confirm.** Signing in to the user's existing account, with their vault credential, on the verified domain, is pre-approved: submit it without asking. Then check the page really is logged in before reporting success.

### Where to stop

- First-time vault login (`bitwarden-use login`): the user types the master password once. After that, unlocks run without asking (see step 2).
- Wrong password, or the site warns about lockout: do not retry more than once. Report back.
- No vault entry for the site: ask the user. Never guess a password, and never start "forgot password" without their OK. A reset changes the stored credential.
- Do not ask for a code more than twice. Resend loops trigger rate limits and account locks.
- Creating an account, adding a payment method, or changing security settings is not logging in. The usual submit-approval rule applies.

### Credential rules

1. Treat every credential and code as high sensitivity. Default to the redacted `login` output; use `--reveal` only at the instant of filling, and never put a password or code in a final response.
2. Do not store, cache, or write a credential or code anywhere. Re-read from the vault each time; codes are single-use.
3. Never ask for, capture, store, or echo the master password. Unlocking is fine (keychain or the pinentry dialog); seeing or typing the password is not.
4. A Touch ID prompt from `bitwarden-use` is intended; never work around it.

### Vault setup (agent-driven)

The CLI uses `bitwarden-use`, and plain `rbw` (its upstream: same agent and database) only when bitwarden-use is not installed. Under `bitwarden-use`, `login --domain` matches each entry's stored URIs (so `jp.mercari.com` finds an entry named `メルカリ`), orients without Touch ID, and on `--reveal` prompts once for the entry it matched. The backup key lives there too, as `profile-use age key` in the `profile-use` folder.

When `vault-status` shows the CLI missing, install and configure it in one command yourself:

```bash
python3 scripts/profile_use.py vault-setup --install --base-url <server-url> --email <account-email>
```

Get the server URL from the user (or one they gave earlier, e.g. `https://bit.leeguoo.com`) and the email from `contact.email`; ask only for what is genuinely unknown. If `next_step` says to run `bitwarden-use login`, the user runs that one command (`! bitwarden-use login && bitwarden-use unlock --keychain-store`) and types the master password. `--keychain-store` saves it in the macOS login keychain, so every later unlock happens without a prompt.

`vault-status` also reports `code_sources`: whether `message-use` and `mail-use` are installed. If one is missing, the matching codes have to come from the user. Offer to install it: `curl -fsSL https://raw.githubusercontent.com/leeguooooo/<name>/main/install.sh | sh`. message-use also needs Full Disk Access for the terminal; mail-use needs an account configured (`mail-use account`).

```bash
python3 scripts/profile_use.py vault-status                          # CLI, server, unlocked, code sources (no secrets)
python3 scripts/profile_use.py vault-unlock                          # unlock: keychain first, else the password dialog
python3 scripts/profile_use.py login --domain example.com            # redacted: user t***@x.com / password ********
python3 scripts/profile_use.py login --domain example.com --reveal   # raw user + password + totp — only at fill time
python3 scripts/profile_use.py login --name "GitHub" --user me@x.com # one entry / one account
python3 scripts/profile_use.py code --wait 120s --from GitHub        # newest SMS/email code that arrives from now on
python3 scripts/profile_use.py code --via mail --since 30m           # newest email code from the last 30 minutes
```

## profile-use vs memory-use

Two stores, split by what the fact is about:

| The fact is… | Store |
|---|---|
| About the person: name, address, phone, IDs, bank/card, family, health, employment contracts, document scans | profile-use |
| About how things were done: NAS, VPN, servers, ports, configs, decisions, rollbacks, todos | memory-use (`leeguooooo/personal-memory`) |

Rule of thumb: if it would be typed into a form or must be redacted in a summary, it belongs here. If a future session reads it to operate a machine, it belongs in memory-use. memory-use notes never hold personal values, only pointers such as "in profile-use `bank.accounts[0]`". When one task produces both (new-computer setup needs a VPN note and a restored profile), write each to its own store.

## Leak Scan

The code repo is public. Real values once reached it as doc and test examples in reshaped form (full-width digits, 番/号 instead of hyphens), so every commit is now checked against the real profile:

```bash
./install.sh                                              # once per checkout: link the skill, enable the pre-commit hook
python3 scripts/profile_use.py leak-scan --staged         # what the hook runs
python3 scripts/profile_use.py leak-scan --history        # audit every commit
python3 scripts/profile_use.py leak-scan docs/ README.md  # files or directories
some-command | python3 scripts/profile_use.py leak-scan --stdin
```

It normalises full-width text and 丁目/番/号, matches whole values plus address and name fragments, prints `file:line` and the dot-path, never the value, and exits 1 on a hit. Any other repo (memory-use, a public tool's docs) can call it before committing; with no local profile it exits 0.

Examples in docs and tests must use placeholders (`100-0001`, `千代田区千代田`, `1-2-3`, `Yamada Taro`), never a value copied from a real form. Mark a genuine false positive with `profile-use: allow` on that line.

## Upgrade

When a `profile_use.py` command prints `profile-use has a newer version on GitHub`, tell the user and offer to run `python3 scripts/profile_use.py upgrade`. It refreshes every installed copy of this skill: `git pull --ff-only` for a checkout, `claude plugin update` for the Claude Code plugin, and it prints `npx skills update profile-use` for a copied folder. Check without changing anything: `upgrade --check` (or `--json`). The user may also just say "升级 profile-use".

Whole family: `curl -fsSL https://raw.githubusercontent.com/leeguooooo/plugins/main/upgrade-use-family.sh | sh`.

## Sync Guidance

Read `references/sync-model.md` when choosing or explaining where profile data should live.

Default recommendation:

- Use iCloud Drive for a single user's private plaintext profile on Apple devices.
- Use a password manager for payment cards, bank accounts, passwords, and one-time codes.
- Use GitHub only for the public skill code, profile schema, examples, or encrypted profile backups. Never put plaintext personal data in a public repository.

## Output Rules

- Final answers should say what was filled and what remains, using redacted values.
- Do not paste full card numbers, bank accounts, government IDs, or addresses into final responses unless the user explicitly asked to display them.
- If a profile file was created, report its local path and remind the user it contains placeholders until they edit it.

---
name: personal-autofill
description: Safely use a user's private local personal profile to help fill registration, signup, checkout, banking, KYC, and onboarding forms. Use when the user asks to enter or reuse identity details such as name, address, phone, postal code, email, birthdate, payment card, bank account, tax ID, or other personal data. Prioritize privacy, redaction, consent before submission, and local/iCloud/encrypted profile sources rather than storing personal data in chat or Git.
---

# Personal Autofill

Use a private profile as the source of truth for repetitive registration and checkout fields. The skill helps map form labels to profile fields, fill only what is needed, and keep sensitive values out of chat, logs, screenshots, repos, and PRs.

## Privacy Rules

1. Never invent personal data. If a field is missing, ask the user or leave it blank.
2. Do not store real personal data in the skill repo, memory, issue trackers, PRs, screenshots, or final responses.
3. Use redacted summaries by default. Reveal full values only when the user explicitly asks and the current task requires it.
4. Treat payment cards, bank accounts, government IDs, tax IDs, passwords, security answers, and medical fields as high sensitivity. Ask for explicit confirmation before entering or revealing them.
5. Do not submit a registration, KYC, checkout, banking, or payment form until the user explicitly approves the final submit action.
6. If browser automation is used, verify the real domain and purpose before filling. Stop on suspicious, unrelated, or typosquatted domains.

## Profile Source

Prefer the helper script:

```bash
python3 scripts/personal_autofill.py path
python3 scripts/personal_autofill.py doctor
python3 scripts/personal_autofill.py init --profile personal
python3 scripts/personal_autofill.py show --profile personal
python3 scripts/personal_autofill.py values --profile personal
python3 scripts/personal_autofill.py values --profile personal contact.email address.postal_code
python3 scripts/personal_autofill.py get --profile personal contact.email address.postal_code
python3 scripts/personal_autofill.py set --profile personal address.postal_code "1000001"
python3 scripts/personal_autofill.py list-fields --profile personal --filled
```

### Redacted vs. raw: pick the right command

This is the most important rule for autofill. Two output modes exist and they are not interchangeable:

- **`values`** returns RAW values. Use it for every value you actually type into a form. With no fields it dumps all filled low/medium fields as a flat `{dotpath: value}` map ready to map onto form labels; it excludes high-sensitivity fields unless you name them or pass `--include-sensitive`.
- **`show` / `get`** return REDACTED values by default (names, email, phone, address lines, card, bank, IDs, notes are masked). Use these only to orient or to report back to the user. Pass `--reveal` to unmask.

NEVER type a redacted/masked value into a form. `get contact.email` returns `t***@example.com`; filling that breaks the registration. To fill, use `values contact.email` (or `get --reveal`). When in doubt for filling: use `values`.

Default location order:

1. `$PERSONAL_AUTOFILL_DIR`
2. `$HOME/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/personal-autofill`
3. `$HOME/.config/personal-autofill`

The iCloud rule checks the iCloud Drive root (`com~apple~CloudDocs`) and creates `Agent Profiles/personal-autofill` on first write. Use `doctor` when a profile unexpectedly lands in `.config`.

Use `references/profile-template.json` for the editable shape. Use `references/profile-schema.json` for field names and sensitivity hints.

## Growing The Profile

Expect the profile to grow over time as real registrations reveal new fields. When a form asks for information that is not already in the profile:

1. Ask the user for the value only if it is required for the current registration.
2. Decide whether it is reusable. Save stable values such as alternate emails, shipping addresses, invoice names, furigana, company details, and country-specific address variants. Do not save one-time codes, session tokens, CAPTCHA text, temporary invitation links, or site passwords.
3. Ask before writing high-sensitivity or newly invented field paths.
4. Add the field with `set`:

```bash
python3 scripts/personal_autofill.py set --profile personal identity.name_kana "..."
python3 scripts/personal_autofill.py set --profile personal address.jp.prefecture "..."
python3 scripts/personal_autofill.py set --profile personal preferences.newsletter_opt_in false --json
```

5. Confirm with redacted reads:

```bash
python3 scripts/personal_autofill.py get --profile personal identity.name_kana address.jp.prefecture
```

Use flexible nested paths when a country, site, or tenant needs a special variant. Examples: `address.jp.*`, `address.us.*`, `contact.work_email`, `invoice.jp.qualified_invoice_name`.

## Fill Workflow

1. Identify the form's site, purpose, and profile to use. Default to `personal` unless the user names another profile such as `work`, `family`, or `jp`.
2. Inspect the form labels and required fields. Build a mapping from labels to profile paths; do not rely only on placeholder text.
3. Orient with redacted `show` to see the shape, then read the exact values you will type with `values` (raw). Use `values` with no fields to get a flat map of all filled low/medium fields at once.
4. Fill low-sensitivity fields directly when the user asked for autofill, using the raw `values` output. Examples: name, email, phone, address, postal code.
5. For high-sensitivity fields (`payment`, `bank`, `government_id`, `tax`, birthdate, gender), show a redacted summary and ask for confirmation before filling; fetch the raw value with an explicit `values payment.card.number` only at the moment of filling.
6. Before submission, summarize the fields that were filled using redacted `show`/`get` values and wait for an explicit submit approval.

## Field Mapping Hints

- `identity.full_name`: full legal name or display name, depending on the form.
- `identity.family_name`, `identity.given_name`: split-name fields.
- `contact.email`, `contact.phone`, `contact.phone_country_code`: email and telephone fields.
- `address.country`, `address.region`, `address.city`, `address.line1`, `address.line2`, `address.postal_code`: address fields.
- `payment.card.*`: card fields; always high sensitivity.
- `bank.*`: bank transfer or withdrawal fields; always high sensitivity.
- `government_id.*`, `tax.*`: identity verification fields; always high sensitivity.
- `preferences.*`: marketing opt-in, locale, newsletter, and delivery preferences.
- `invoice.*`: billing name, tax invoice name, receipt name, or business invoice details.
- `site_overrides.<domain>.*`: a value required only by one service; use this sparingly.

If a site has country-specific formatting rules, preserve the profile value unless the form rejects it. Normalize only after checking the visible validation message.

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

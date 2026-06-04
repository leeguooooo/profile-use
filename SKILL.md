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
python3 scripts/personal_autofill.py init --profile personal
python3 scripts/personal_autofill.py show --profile personal
python3 scripts/personal_autofill.py get --profile personal contact.email address.postal_code
```

Default location order:

1. `$PERSONAL_AUTOFILL_DIR`
2. `$HOME/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/personal-autofill`
3. `$HOME/.config/personal-autofill`

Use `references/profile-template.json` for the editable shape. Use `references/profile-schema.json` for field names and sensitivity hints.

## Fill Workflow

1. Identify the form's site, purpose, and profile to use. Default to `personal` unless the user names another profile such as `work`, `family`, or `jp`.
2. Inspect the form labels and required fields. Build a mapping from labels to profile paths; do not rely only on placeholder text.
3. Read only the needed profile fields with the helper script. Start with redacted `show` when orienting; use `get` for exact fields.
4. Fill low-sensitivity fields directly when the user asked for autofill. Examples: name, email, phone, address, postal code.
5. For high-sensitivity fields, show a redacted summary and ask for confirmation before filling.
6. Before submission, summarize the fields that were filled using redacted values and wait for an explicit submit approval.

## Field Mapping Hints

- `identity.full_name`: full legal name or display name, depending on the form.
- `identity.family_name`, `identity.given_name`: split-name fields.
- `contact.email`, `contact.phone`, `contact.phone_country_code`: email and telephone fields.
- `address.country`, `address.region`, `address.city`, `address.line1`, `address.line2`, `address.postal_code`: address fields.
- `payment.card.*`: card fields; always high sensitivity.
- `bank.*`: bank transfer or withdrawal fields; always high sensitivity.
- `government_id.*`, `tax.*`: identity verification fields; always high sensitivity.
- `preferences.*`: marketing opt-in, locale, newsletter, and delivery preferences.

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

# profile-use

A skill for safely filling signup, registration, checkout, banking, KYC, and onboarding forms from a private local profile.

It is intentionally split into two parts:

- This public repo: skill instructions, profile schema, placeholder template, and helper script.
- Your private profile: local/iCloud/password-manager data that never belongs in Git.

## Install

```bash
npx skills add leeguooooo/profile-use
```

Or install from the GitHub URL:

```bash
npx skills add https://github.com/leeguooooo/profile-use
```

## Create a private profile

```bash
python3 scripts/profile_use.py init --profile personal
python3 scripts/profile_use.py path --profile personal
python3 scripts/profile_use.py doctor --profile personal
```

By default, the script uses iCloud Drive when available:

```text
~/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/profile-use
```

The script checks the iCloud Drive root and creates `Agent Profiles/profile-use` on first write. If iCloud Drive is unavailable, it falls back to `~/.config/profile-use`.

Override the location with:

```bash
export PROFILE_USE_DIR="/private/path/to/profile-use"
```

## Sync recommendation

Use iCloud Drive for the everyday local profile. Use a password manager for cards, bank accounts, passwords, recovery codes, and government IDs. Use GitHub only for this skill, schemas, placeholder examples, or encrypted backups.

Never commit plaintext profile data.

## Commands

```bash
python3 scripts/profile_use.py show --profile personal
python3 scripts/profile_use.py values --profile personal
python3 scripts/profile_use.py values --profile personal contact.email address.postal_code
python3 scripts/profile_use.py get --profile personal contact.email address.postal_code
python3 scripts/profile_use.py get --profile personal --reveal contact.email
python3 scripts/profile_use.py set --profile personal contact.email "me@example.com"
python3 scripts/profile_use.py set --profile personal preferences.marketing_opt_in false --json
python3 scripts/profile_use.py unset --profile personal preferences.marketing_opt_in
python3 scripts/profile_use.py list-fields --profile personal --filled
python3 scripts/profile_use.py check --profile personal
```

Original document images (residence card, bank card, My Number card, ...) for forms that need a photo upload:

```bash
python3 scripts/profile_use.py attach ~/Downloads/card.jpg --doc residence_card_front --label "在留カード 表面" --move
python3 scripts/profile_use.py attachments --profile personal
python3 scripts/profile_use.py attachment-path --doc residence_card_front
python3 scripts/profile_use.py detach --doc residence_card_front
```

Attachments are stored next to the profile (`<profile-dir>/attachments/<profile>/`, mode 600) so they sync with it and never enter Git; metadata lives under `documents.<doc>` in the profile JSON.

Two output modes:

- **`values`** — RAW values, for typing into forms. No fields = a flat `{dotpath: value}` map of all filled low/medium fields (high-sensitivity fields are excluded unless named or `--include-sensitive`).
- **`show` / `get`** — REDACTED by default, for orienting or reporting back. Add `--reveal` to unmask.

Never type a redacted value (`t***@example.com`) into a form — use `values` for filling.

## Adding information over time

The profile is meant to grow during real registration work. When a site asks for a reusable field that is missing, add it with a dot path:

```bash
python3 scripts/profile_use.py set --profile personal identity.name_kana "..."
python3 scripts/profile_use.py set --profile personal address.jp.prefecture "..."
python3 scripts/profile_use.py set --profile personal invoice.receipt_name "..."
```

Use flexible nested paths for country-specific or site-specific fields. Do not save one-time codes, CAPTCHA text, temporary links, passwords, or session tokens.

# personal-autofill

A skill for safely filling signup, registration, checkout, banking, KYC, and onboarding forms from a private local profile.

It is intentionally split into two parts:

- This public repo: skill instructions, profile schema, placeholder template, and helper script.
- Your private profile: local/iCloud/password-manager data that never belongs in Git.

## Install

```bash
npx skills add leeguooooo/personal-autofill
```

Or install from the GitHub URL:

```bash
npx skills add https://github.com/leeguooooo/personal-autofill
```

## Create a private profile

```bash
python3 scripts/personal_autofill.py init --profile personal
python3 scripts/personal_autofill.py path --profile personal
```

By default, the script uses iCloud Drive when available:

```text
~/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/personal-autofill
```

Override the location with:

```bash
export PERSONAL_AUTOFILL_DIR="/private/path/to/personal-autofill"
```

## Sync recommendation

Use iCloud Drive for the everyday local profile. Use a password manager for cards, bank accounts, passwords, recovery codes, and government IDs. Use GitHub only for this skill, schemas, placeholder examples, or encrypted backups.

Never commit plaintext profile data.

## Commands

```bash
python3 scripts/personal_autofill.py show --profile personal
python3 scripts/personal_autofill.py get --profile personal contact.email address.postal_code
python3 scripts/personal_autofill.py get --profile personal --reveal contact.email
python3 scripts/personal_autofill.py set --profile personal contact.email "me@example.com"
python3 scripts/personal_autofill.py set --profile personal preferences.marketing_opt_in false --json
python3 scripts/personal_autofill.py unset --profile personal preferences.marketing_opt_in
python3 scripts/personal_autofill.py list-fields --profile personal --filled
python3 scripts/personal_autofill.py check --profile personal
```

The default output is redacted. Use `--reveal` only when the current task truly needs exact values.

## Adding information over time

The profile is meant to grow during real registration work. When a site asks for a reusable field that is missing, add it with a dot path:

```bash
python3 scripts/personal_autofill.py set --profile personal identity.name_kana "..."
python3 scripts/personal_autofill.py set --profile personal address.jp.prefecture "..."
python3 scripts/personal_autofill.py set --profile personal invoice.receipt_name "..."
```

Use flexible nested paths for country-specific or site-specific fields. Do not save one-time codes, CAPTCHA text, temporary links, passwords, or session tokens.

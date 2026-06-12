<p align="center">
  <img src="assets/hero.png" alt="a residence card, drawn very badly" width="640">
</p>

# profile-use

[中文](README.zh-CN.md) | **English**

One private profile. Every signup form. An agent skill that fills registration, signup, checkout, banking, KYC, and onboarding forms from a single local profile — without your personal data ever touching a Git repo, a chat log, or anyone else's server.

Part of the `*-use` family (`iphone-use`, browser automation, computer use): those skills drive the device, **profile-use is what they fill the forms with**.

## "Is my data going to leak?"

<p align="center">
  <img src="assets/privacy.png" alt="an exhausted padlock crossing out git, chat and spying clouds" width="360">
</p>

That is the first question that matters, so here is the whole model:

| Your data | Where it is | Where it is NOT |
| --- | --- | --- |
| Profile JSON (name, address, phone, bank, IDs) | Your iCloud Drive or `~/.config`, file mode 600 | Not in this repo, not in any cloud service of ours (we don't have one), not in the model's training data |
| Original document images (residence card, bank card, ...) | Next to the profile, mode 600 | Not in Git, not in `/tmp` leftovers — the skill cleans up after itself |
| Values shown in chat / final answers | Redacted by default (`t***@example.com`, `********2590`) | Raw values appear in chat only when you explicitly ask |

Hard rules baked into the skill (`SKILL.md`):

1. **Never invents data.** Missing field → asks you or leaves it blank.
2. **Redacted by default.** The agent orients with masked values; raw values are read only at the exact moment of typing into a form.
3. **High-sensitivity gate.** Payment cards, bank accounts, government IDs, tax IDs, birthdate: per-use confirmation before they are filled or revealed.
4. **Nothing auto-submits.** Forms are submitted only after your explicit approval of a redacted summary.
5. **Document uploads confirmed per upload.** Even if text autofill was already approved.
6. **Domain check.** Browser automation verifies the real domain before filling; stops on typosquats.

This public repo contains code, schema, and placeholder templates only. `.gitignore` blocks `*.profile.json`; plaintext personal data never belongs in Git, ours or yours.

### What about the LLM itself, and API relays?

Honest answer — there are three channels, and they are not equally safe:

| Channel | What it sees | Verdict |
| --- | --- | --- |
| The helper script (`scripts/profile_use.py`) | Local file I/O only. One file, zero network code — audit it yourself. | Nothing ever leaves your machine through the script. |
| The model provider (Claude / OpenAI / ...) | Values the agent reads DO enter the conversation context and are sent to the model API over TLS. This is inherent to any LLM-driven autofill. | As trustworthy as your provider's API data policy (major providers don't train on API traffic by default). Redaction-by-default keeps most of the session masked; raw values are fetched per-field, only at the moment of filling. |
| **Third-party API relays (中转站 / resellers / proxies)** | The **full plaintext** of every request, including any raw value the agent reads. | **Don't.** If you route your agent through a relay you wouldn't hand your ID card to, this skill cannot protect you. Use official endpoints, an enterprise gateway you control, or a locally-hosted model. |

Practical rules:

- Running through an official provider endpoint: the built-in redaction + per-field raw reads + high-sensitivity gates are designed exactly for this case.
- Running through any relay or unknown proxy: let the agent fill the low-sensitivity fields, and type card numbers / IDs / bank details yourself.
- Fully local model (Ollama, llama.cpp, ...): nothing leaves the machine at all — the strongest configuration.
- The skill never bulk-dumps high-sensitivity fields into context: `values` excludes them unless you name a field explicitly, so a single fill exposes only the fields that form actually needed.

## What it does

<p align="center">
  <img src="assets/how-it-works.png" alt="iCloud file, a derpy robot, and a signup form connected by wobbly arrows" width="640">
</p>

You keep one `personal.profile.json` (plus optional `work`, `family`, `jp`, ... profiles). When any form needs your details, the agent maps form labels to profile dot-paths and types the right values:

- **Text fields** — name, furigana, birthdate, address (with country-specific variants like `address.jp.*`), phone, emails, postal code, bank, tax ID, invoice names, preferences.
- **Original document images** — residence card photos, My Number card, bank card: stored as attachments next to the profile, fetched by path when a KYC form wants a photo upload.
- **It grows** — every real registration that reveals a new reusable field adds it back to the profile, so the next form is faster.

## Works with your automation stack

<p align="center">
  <img src="assets/automation.png" alt="a computer, a phone and a laptop sadly filling forms from one profile" width="640">
</p>

profile-use is the **data layer**. Pair it with whatever drives the screen:

| Driver | Scenario |
| --- | --- |
| Browser automation (Claude in Chrome, agent-browser, computer use) | Auto-register on websites, checkout, KYC photo upload |
| `iphone-use` | Onboarding flows inside native iOS apps |
| Desktop automation (computer use, cua-driver) | Native desktop app sign-ups |

The flow is always the same: the driver reads the form → profile-use supplies values (raw only at fill time) → high-sensitivity fields and the final submit wait for your confirmation.

## Install

```bash
npx skills add leeguooooo/profile-use
```

Or from the GitHub URL:

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

Two output modes:

- **`values`** — RAW values, for typing into forms. No fields = a flat `{dotpath: value}` map of all filled low/medium fields (high-sensitivity fields are excluded unless named or `--include-sensitive`).
- **`show` / `get`** — REDACTED by default, for orienting or reporting back. Add `--reveal` to unmask.

Never type a redacted value (`t***@example.com`) into a form — use `values` for filling.

## Original document images

For forms that need a photo upload (KYC, payroll, ID verification):

```bash
python3 scripts/profile_use.py attach ~/Downloads/card.jpg --doc residence_card_front --label "在留カード 表面" --move
python3 scripts/profile_use.py attachments --profile personal
python3 scripts/profile_use.py attachment-path --doc residence_card_front
python3 scripts/profile_use.py detach --doc residence_card_front
```

Attachments are stored next to the profile (`<profile-dir>/attachments/<profile>/`, mode 600) so they sync with it and never enter Git; metadata (label, source, added date, sha256) lives under `documents.<doc>` in the profile JSON.

## Adding information over time

The profile is meant to grow during real registration work. When a site asks for a reusable field that is missing, add it with a dot path:

```bash
python3 scripts/profile_use.py set --profile personal identity.name_kana "..."
python3 scripts/profile_use.py set --profile personal address.jp.prefecture "..."
python3 scripts/profile_use.py set --profile personal invoice.receipt_name "..."
```

Use flexible nested paths for country-specific or site-specific fields. Do not save one-time codes, CAPTCHA text, temporary links, passwords, or session tokens.

## Sync recommendation

Use iCloud Drive for the everyday local profile. Use a password manager for cards, bank accounts, passwords, recovery codes, and government IDs. Use GitHub only for this skill, schemas, placeholder examples, or encrypted backups.

Never commit plaintext profile data.

## Migrating from personal-autofill

This project used to be called `personal-autofill`. Old installs keep working — GitHub redirects the repo, the script honors the legacy `PERSONAL_AUTOFILL_DIR` env var, and a legacy `personal-autofill` data directory is used as a fallback whenever the new one doesn't exist. To converge on the new name:

```bash
# 1. Reinstall the skill under its new name
npx skills remove personal-autofill -g
npx skills add leeguooooo/profile-use -g

# 2. Rename the data directory (optional — the fallback works forever)
mv "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/personal-autofill" \
   "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/profile-use"

# 3. If you exported the old env var, rename it
export PROFILE_USE_DIR="..."   # was PERSONAL_AUTOFILL_DIR
```

## Why do the illustrations look like that

They were drawn the way this project handles your data: locally, badly, and with full transparency.

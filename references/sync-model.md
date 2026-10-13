# Sync Model

Use this guide when deciding where profile data should live.

## Data ownership

| Example | Workflow owner | Authoritative value |
| --- | --- | --- |
| Address, furigana, housing preferences, residence-renewal checklist | profile-use | Private profile and local documents |
| Personal card, identity or bank account | profile-use | Ordinary metadata in the profile; secret number in Bitwarden |
| NAS topology, SSH connection instructions, troubleshooting decisions | memory-use | Private technical notes |
| Login password, API token, passkey, SSH private key | bitwarden-use | Vault entry |

Sensitivity decides where a value is stored; purpose decides which workflow reads it.
Do not maintain two editable sources for the same secret. Backups retain historical
values and are not authoritative for daily reads. Bitwarden stores secrets but does
not replace profile-use's field mapping, regional formatting or consent workflow.

## Vault references and backup

`profile_use.py link-vault FIELD --item UUID --vault-field FIELD --dry-run` checks a
local value against a freshly synced vault field. `--yes` replaces the matching
local value with a `$vault` reference. No plaintext cache is retained in the profile.
Use `--encoding json` for typed JSON custom fields. Default masked reads show
`[vault]` without contacting the vault; explicit reads use its existing unlock,
reveal and audit policy. Failed reads have no plaintext fallback.

`profile_use.py sync --profile personal --dry-run` previews a one-way verified
backup. `--yes` stores profile JSON and original documents in the vault. References
stay references; linked native cards are not written back from profile metadata.
The old `bwu profile sync FILE` delegates here. Existing unlinked native projections
and snapshots are copies. Neither command merges edits from two stores.

Original documents remain local for form uploads; the vault holds verified encrypted
backup copies. A document image can still contain an ID or card number after its
extracted text field is linked. Linking changes the JSON field, not the image or
historical backups. Restore and access policy for those copies remain separate.

## Recommended Default: iCloud Drive

iCloud Drive is the best default for a single Apple user because it syncs across the user's own Macs, stays outside Git history, and works with normal local file reads.

Default path:

```text
~/Library/Mobile Documents/com~apple~CloudDocs/Agent Profiles/profile-use
```

The helper script checks whether the iCloud Drive root exists and creates `Agent Profiles/profile-use` on first write. It should not require the `Agent Profiles` folder to already exist. If it falls back to `~/.config/profile-use`, run:

```bash
python3 scripts/profile_use.py doctor --profile personal
```

Use plaintext here only if the Mac account and iCloud account are trusted. Keep high-sensitivity values such as card CVV, bank accounts, passwords, recovery codes, and government IDs in a password manager when possible.

## GitHub

Use GitHub for:

- the public skill code
- schema and placeholder templates
- encrypted profile backups
- issue discussions that do not include real personal data

Do not commit plaintext profiles to public or private repositories. Private repos still create avoidable blast radius through forks, logs, Actions, local clones, and accidental sharing.

If GitHub sync is required, commit only encrypted files such as:

```text
profiles/personal.profile.json.age
profiles/work.profile.json.age
```

Use a local decrypt step outside the skill before running form fill tasks. Do not ask the agent to paste decrypted contents into chat.

## Password Managers

Use 1Password, Bitwarden, Apple Passwords, or another password manager for:

- card numbers and CVV
- bank accounts
- passwords and passkeys
- recovery codes
- government IDs

The skill can fill low-sensitivity fields from the local JSON profile and ask the user to approve or provide high-sensitivity values from the password manager at the point of use.

For Bitwarden and self-hosted **Vaultwarden**, this is wired up: `profile_use.py login --domain <host>` reads a single credential live through the `bitwarden-use` CLI (or plain `rbw`) and returns it redacted by default (raw only with `--reveal`). Passwords are never copied into the profile JSON — the vault stays the single source of truth, and the unlock lives in its background agent. See the "Login Credentials" section of `SKILL.md` for setup and usage.

## Environment Variables

Use environment variables only for temporary automation sessions. They are convenient for CI-like runs but can leak through process listings, shell history, and logs.

Supported variable:

```bash
export PROFILE_USE_DIR="/private/path/to/profiles"
```

## Decision Table

| Need | Best storage |
|---|---|
| Solo Mac/iPhone profile sync | iCloud Drive |
| Public installable skill | GitHub repo with templates only |
| Encrypted backup | GitHub private repo or iCloud with age/sops-encrypted files |
| Payment and banking secrets | Password manager |
| One-off form fill | Current chat plus no memory, or temporary local profile |

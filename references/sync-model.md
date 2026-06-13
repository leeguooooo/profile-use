# Sync Model

Use this guide when deciding where profile data should live.

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

For Bitwarden and self-hosted **Vaultwarden**, this is wired up: `profile_use.py login --domain <host>` reads a single credential live through the `rbw` CLI and returns it redacted by default (raw only with `--reveal`). Passwords are never copied into the profile JSON — the vault stays the single source of truth, and the unlock lives in `rbw-agent`. See the "Login Credentials" section of `SKILL.md` for setup and usage.

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

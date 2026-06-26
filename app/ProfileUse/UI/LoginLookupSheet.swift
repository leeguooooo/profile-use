import AppKit
import SwiftUI

/// Reads a login credential live from the rbw / Bitwarden vault. Nothing is
/// stored; the master password is never requested here — if the vault is locked
/// we surface the `rbw unlock` command for the user to run themselves.
struct LoginLookupSheet: View {
    @ObservedObject var model: ProfileModel
    @Environment(\.dismiss) private var dismiss

    @State private var domain = ""
    @State private var status: VaultStatus?
    @State private var result: LoginResult?
    @State private var busy = false
    @State private var checked = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("Look up login", systemImage: "key.horizontal")
                .font(.title2.weight(.semibold))

            if !checked {
                ProgressView().frame(maxWidth: .infinity)
            } else if status?.rbwInstalled != true {
                fix("rbw (Bitwarden CLI) is not installed.", command: "profile-use vault-setup --install")
            } else if status?.unlocked != true {
                fix("Vault is locked.", command: "rbw unlock")
            } else {
                lookupForm
            }

            if let err = model.lastError { Text(err).font(.caption).foregroundStyle(.orange) }

            HStack {
                Spacer()
                Button("Done") { model.lastError = nil; dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 460)
        .task {
            status = await model.checkVaultStatus()
            checked = true
        }
    }

    private var lookupForm: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let email = status?.email { Text("Vault: \(email)").font(.caption).foregroundStyle(.secondary) }
            HStack(spacing: 8) {
                TextField("Domain (e.g. example.com)", text: $domain)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { lookup() }
                Button("Look up") { lookup() }
                    .buttonStyle(.borderedProminent)
                    .disabled(domain.trimmingCharacters(in: .whitespaces).isEmpty || busy)
            }
            if busy { ProgressView() }
            if let r = result { resultView(r) }
            Text("Credentials are read live from the vault and never stored in your profile.")
                .font(.caption2).foregroundStyle(.tertiary)
        }
    }

    @ViewBuilder
    private func resultView(_ r: LoginResult) -> some View {
        if r.ok {
            VStack(alignment: .leading, spacing: 8) {
                if let item = r.item { Text(item).font(.headline) }
                LabeledContent("Username") {
                    HStack {
                        Text(r.username ?? "—").foregroundStyle(.secondary)
                        Button { Task { await model.copyUsername(domain: domain) } } label: { Image(systemName: "doc.on.doc") }
                            .buttonStyle(.borderless)
                    }
                }
                LabeledContent("Password") {
                    HStack {
                        Text(r.password ?? "••••••••").foregroundStyle(.secondary)
                        Button { Task { await model.copyPassword(domain: domain) } } label: {
                            Label("Reveal & copy", systemImage: "lock.shield")
                        }
                        .buttonStyle(.bordered)
                    }
                }
                if let totp = r.totp { LabeledContent("TOTP") { Text(totp).foregroundStyle(.secondary) } }
            }
            .infoCard(border: .orange)
        } else if let candidates = r.candidates, !candidates.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(r.reason ?? "Multiple matches").font(.callout)
                ForEach(candidates, id: \.name) { c in
                    Text("• \(c.name)\(c.user.map { " (\($0))" } ?? "")").font(.caption).foregroundStyle(.secondary)
                }
            }.infoCard(border: .secondary)
        } else {
            VStack(alignment: .leading, spacing: 4) {
                Text(r.reason ?? "No match.").font(.callout)
                if let hint = r.hint { Text(hint).font(.caption).foregroundStyle(.secondary) }
            }.infoCard(border: .secondary)
        }
    }

    private func fix(_ message: String, command: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(message, systemImage: "lock.trianglebadge.exclamationmark").foregroundStyle(.orange)
            HStack {
                Text(command).font(.system(.callout, design: .monospaced))
                    .padding(8).background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 6))
                Button { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(command, forType: .string) } label: {
                    Image(systemName: "doc.on.doc")
                }.buttonStyle(.borderless)
            }
            Text("Run it in Terminal, then reopen this.").font(.caption).foregroundStyle(.secondary)
        }
        .infoCard(border: .orange)
    }

    private func lookup() {
        let d = domain.trimmingCharacters(in: .whitespaces)
        guard !d.isEmpty else { return }
        busy = true
        Task {
            result = await model.lookupLogin(domain: d)
            busy = false
        }
    }
}

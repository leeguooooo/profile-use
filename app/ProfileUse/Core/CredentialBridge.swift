import Foundation

/// Status of the rbw / Bitwarden vault, from `profile_use.py vault-status`.
struct VaultStatus: Codable, Equatable {
    let rbwInstalled: Bool?
    let unlocked: Bool?
    let email: String?
    let baseUrl: String?
}

/// One credential lookup result from `profile_use.py login`.
struct LoginResult: Codable, Equatable {
    struct Candidate: Codable, Equatable { let name: String; let user: String? }
    let ok: Bool
    let domain: String?
    let item: String?
    let username: String?
    let password: String?
    let totp: String?
    let uris: [String]?
    let reason: String?
    let hint: String?
    let candidates: [Candidate]?
}

/// Reads credentials and linked fields via the bundled profile helper, which
/// delegates unlock/reveal policy to bitwarden-use. The GUI never receives or
/// stores the vault master password; revealed field values stay in session memory.
actor CredentialBridge {
    static let shared = CredentialBridge()

    enum CredError: LocalizedError {
        case noPython, noScript, vaultLocked, notInstalled, lookup(String)
        var errorDescription: String? {
            switch self {
            case .noPython: return "python3 not found. Install the Xcode Command Line Tools or Homebrew python."
            case .noScript: return "Bundled profile_use.py is missing."
            case .vaultLocked: return "Vault is locked. Run: bitwarden-use unlock"
            case .notInstalled: return "bitwarden-use (Bitwarden CLI) is not installed. Run: profile-use vault-setup --install"
            case let .lookup(msg): return msg
            }
        }
    }

    private let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }()

    private func python() -> URL? {
        for p in ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"] {
            if FileManager.default.isExecutableFile(atPath: p) { return URL(fileURLWithPath: p) }
        }
        return nil
    }

    private func scriptPath() -> String? {
        Bundle.main.path(forResource: "profile_use", ofType: "py")
    }

    private func run(_ args: [String]) async throws -> (status: Int32, stdout: Data) {
        guard let py = python() else { throw CredError.noPython }
        guard let script = scriptPath() else { throw CredError.noScript }
        let process = Process()
        process.executableURL = py
        process.arguments = [script] + args
        let outPipe = Pipe(); let errPipe = Pipe()
        process.standardOutput = outPipe; process.standardError = errPipe
        try process.run()
        async let output = readToEnd(outPipe.fileHandleForReading)
        async let errors = readToEnd(errPipe.fileHandleForReading)
        let (out, _) = await (output, errors)
        process.waitUntilExit()
        return (process.terminationStatus, out)
    }

    private func readToEnd(_ h: FileHandle) async -> Data {
        await withCheckedContinuation { c in
            DispatchQueue.global(qos: .userInitiated).async { c.resume(returning: h.readDataToEndOfFile()) }
        }
    }

    func vaultStatus() async throws -> VaultStatus {
        let r = try await run(["vault-status"])
        return try decoder.decode(VaultStatus.self, from: r.stdout)
    }

    func profileValue(profile: String, path: String) async throws -> String {
        let r = try await run(["get", "--profile", profile, path, "--reveal"])
        guard r.status == 0,
              let object = try? JSONSerialization.jsonObject(with: r.stdout) as? [String: Any],
              let value = object[path], !(value is NSNull) else {
            throw CredError.lookup("Vault field could not be read. Check the reference and complete any vault authorization prompt.")
        }
        if let text = value as? String { return text }
        let data = try JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed, .sortedKeys])
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// Look up a credential. `reveal: true` returns the raw password (call only
    /// at the moment of use, after a Touch ID gate). Failure JSON (no/multiple
    /// match) decodes too — check `.ok`.
    func login(domain: String, reveal: Bool, deep: Bool = false) async throws -> LoginResult {
        var args = ["login", "--domain", domain]
        if reveal { args.append("--reveal") }
        if deep { args.append("--deep") }
        let r = try await run(args)
        // login prints JSON on both success and the ok:false failure paths.
        if let result = try? decoder.decode(LoginResult.self, from: r.stdout) { return result }
        let text = String(data: r.stdout, encoding: .utf8) ?? ""
        throw CredError.lookup(text.isEmpty ? "Credential lookup failed." : text)
    }
}

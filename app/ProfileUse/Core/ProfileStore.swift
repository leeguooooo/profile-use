import Foundation

/// Resolves where profiles live and lists/creates them, mirroring
/// `scripts/profile_use.py` exactly (iCloud Drive → ~/.config, legacy fallbacks).
enum ProfileStore {
    private static var home: URL { FileManager.default.homeDirectoryForCurrentUser }

    /// First match wins, per the contract's resolution order.
    static func directory() -> URL {
        let env = ProcessInfo.processInfo.environment
        for key in ["PROFILE_USE_DIR", "PERSONAL_AUTOFILL_DIR"] {
            if let raw = env[key], !raw.isEmpty {
                return URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
            }
        }
        let icloudRoot = home.appendingPathComponent("Library/Mobile Documents/com~apple~CloudDocs")
        if FileManager.default.fileExists(atPath: icloudRoot.path) {
            let new = icloudRoot.appendingPathComponent("Agent Profiles/profile-use")
            let legacy = icloudRoot.appendingPathComponent("Agent Profiles/personal-autofill")
            if !FileManager.default.fileExists(atPath: new.path),
               FileManager.default.fileExists(atPath: legacy.path) { return legacy }
            return new
        }
        let new = home.appendingPathComponent(".config/profile-use")
        let legacy = home.appendingPathComponent(".config/personal-autofill")
        if !FileManager.default.fileExists(atPath: new.path),
           FileManager.default.fileExists(atPath: legacy.path) { return legacy }
        return new
    }

    static func isValidName(_ name: String) -> Bool {
        name.range(of: "^[A-Za-z0-9][A-Za-z0-9_-]*$", options: .regularExpression) != nil
    }

    static func fileURL(for profile: String) -> URL {
        directory().appendingPathComponent("\(profile).profile.json")
    }

    static func attachmentsDir(for profile: String) -> URL {
        directory().appendingPathComponent(profile)
    }

    /// Profile names present on disk (`*.profile.json`), sorted; always includes "personal".
    static func listProfiles() -> [String] {
        let dir = directory()
        let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        var set = Set(names.compactMap { $0.hasSuffix(".profile.json") ? String($0.dropLast(".profile.json".count)) : nil })
        set.insert("personal")
        return set.sorted()
    }
}

/// A live, editable profile JSON document. Backed by NSMutableDictionary so
/// unknown keys round-trip untouched and nested edits are simple.
final class ProfileDocument {
    let profile: String
    private let root: NSMutableDictionary

    init(profile: String, root: NSMutableDictionary) {
        self.profile = profile
        self.root = root
    }

    static func load(profile: String) -> ProfileDocument {
        let url = ProfileStore.fileURL(for: profile)
        if let data = try? Data(contentsOf: url),
           let obj = try? JSONSerialization.jsonObject(with: data, options: [.mutableContainers]) as? NSMutableDictionary {
            return ProfileDocument(profile: profile, root: obj)
        }
        let seed = NSMutableDictionary()
        seed["profile_name"] = profile
        return ProfileDocument(profile: profile, root: seed)
    }

    // MARK: dot-path access

    func string(_ path: String) -> String {
        (value(at: path) as? String) ?? ""
    }

    func bool(_ path: String) -> Bool {
        (value(at: path) as? NSNumber)?.boolValue ?? false
    }

    /// True when a leaf has a non-empty value.
    func isFilled(_ path: String) -> Bool {
        switch value(at: path) {
        case let s as String: return !s.isEmpty
        case is NSNull, nil: return false
        default: return true
        }
    }

    private func value(at path: String) -> Any? {
        var node: Any? = root
        for part in path.split(separator: ".") {
            guard let dict = node as? NSDictionary else { return nil }
            node = dict[String(part)]
        }
        return node
    }

    func setString(_ value: String, at path: String) {
        setRaw(value.isEmpty ? "" : value, at: path)
    }

    func setBool(_ value: Bool, at path: String) {
        setRaw(NSNumber(value: value), at: path)
    }

    private func setRaw(_ value: Any, at path: String) {
        let parts = path.split(separator: ".").map(String.init)
        var node = root
        for part in parts.dropLast() {
            if let child = node[part] as? NSMutableDictionary {
                node = child
            } else {
                let child = NSMutableDictionary()
                node[part] = child
                node = child
            }
        }
        if let last = parts.last { node[last] = value }
    }

    var documentsMap: [String: [String: Any]] {
        ((root["documents"] as? NSDictionary) as? [String: [String: Any]]) ?? [:]
    }

    func setDocument(_ meta: NSDictionary, key: String) {
        let docs: NSMutableDictionary
        if let existing = root["documents"] as? NSMutableDictionary {
            docs = existing
        } else {
            docs = NSMutableDictionary()
            root["documents"] = docs
        }
        docs[key] = meta
    }

    func removeDocument(key: String) {
        (root["documents"] as? NSMutableDictionary)?.removeObject(forKey: key)
    }

    // MARK: serialize + atomic 0600 write

    func save() throws {
        let dir = ProfileStore.directory()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        var data = try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .withoutEscapingSlashes, .sortedKeys])
        data.append(0x0A) // trailing newline

        let url = ProfileStore.fileURL(for: profile)
        let tmp = dir.appendingPathComponent(".\(profile).profile.json.tmp")
        FileManager.default.createFile(atPath: tmp.path, contents: nil, attributes: [.posixPermissions: 0o600])
        try data.write(to: tmp)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: tmp.path)
        _ = try FileManager.default.replaceItemAt(url, withItemAt: tmp)
    }
}

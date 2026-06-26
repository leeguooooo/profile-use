import CryptoKit
import Foundation

/// One attached document image (residence card, bank card, …). Stored next to
/// the profile JSON, mode 0600, tracked under `documents.<key>` in the profile.
struct DocEntry: Identifiable {
    let key: String
    let fileName: String
    let absolutePath: URL
    let exists: Bool
    let label: String?
    let source: String?
    let added: String?
    let sizeBytes: Int?
    var id: String { key }
}

/// Attach / list / remove document images, mirroring the helper's `attach`/`detach`.
enum DocumentManager {
    static func list(profile: String, doc: ProfileDocument) -> [DocEntry] {
        let dir = ProfileStore.attachmentsDir(for: profile)
        return doc.documentsMap
            .sorted { $0.key < $1.key }
            .map { key, meta in
                let fileName = (meta["file"] as? String) ?? key
                let abs = dir.appendingPathComponent(fileName)
                let attrs = try? FileManager.default.attributesOfItem(atPath: abs.path)
                return DocEntry(
                    key: key,
                    fileName: fileName,
                    absolutePath: abs,
                    exists: FileManager.default.fileExists(atPath: abs.path),
                    label: meta["label"] as? String,
                    source: meta["source"] as? String,
                    added: meta["added"] as? String,
                    sizeBytes: (attrs?[.size] as? NSNumber)?.intValue
                )
            }
    }

    /// Copy a file into the attachments dir (0600), record sha256 + metadata, save.
    static func attach(fileURL: URL, key rawKey: String?, profile: String, doc: ProfileDocument) throws {
        let suffix = fileURL.pathExtension.isEmpty ? "" : ".\(fileURL.pathExtension.lowercased())"
        let key = sanitize(rawKey?.isEmpty == false ? rawKey! : fileURL.deletingPathExtension().lastPathComponent)
        let fileName = "\(key)\(suffix)"

        let dir = ProfileStore.attachmentsDir(for: profile)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        let dest = dir.appendingPathComponent(fileName)

        let data = try Data(contentsOf: fileURL)
        if FileManager.default.fileExists(atPath: dest.path) { try FileManager.default.removeItem(at: dest) }
        try data.write(to: dest)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: dest.path)

        let sha = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let meta = NSMutableDictionary()
        meta["file"] = fileName
        meta["source"] = "manual"
        meta["added"] = ISO8601DateFormatter().string(from: Date())
        meta["sha256"] = sha
        doc.setDocument(meta, key: key)
        try doc.save()
    }

    static func remove(key: String, profile: String, doc: ProfileDocument) throws {
        if let entry = list(profile: profile, doc: doc).first(where: { $0.key == key }), entry.exists {
            try? FileManager.default.removeItem(at: entry.absolutePath)
        }
        doc.removeDocument(key: key)
        try doc.save()
    }

    private static func sanitize(_ s: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        let cleaned = s.unicodeScalars.map { allowed.contains($0) ? Character($0) : "_" }
        let result = String(cleaned)
        return result.isEmpty ? "document" : result
    }
}

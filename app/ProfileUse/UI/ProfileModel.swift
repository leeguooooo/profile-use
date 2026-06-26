import AppKit
import SwiftUI

/// The whole app's state: the active profile document, reveal state, and the
/// schema-driven read/write/redaction operations the editor and quick-copy use.
@MainActor
final class ProfileModel: ObservableObject {
    @Published var profiles: [String]
    @Published var activeProfile: String
    @Published var revealed: Set<String> = []
    @Published var dirty = false
    @Published var lastError: String?
    @Published var lastMessage: String?
    /// Bumped on profile switch / reload to force the schema-driven views to refresh.
    @Published private(set) var docVersion = 0

    private(set) var doc: ProfileDocument

    init() {
        let profs = ProfileStore.listProfiles()
        profiles = profs
        let active = profs.first ?? "personal"
        activeProfile = active
        doc = ProfileDocument.load(profile: active)
    }

    // MARK: Profiles

    func switchProfile(_ name: String) {
        activeProfile = name
        doc = ProfileDocument.load(profile: name)
        revealed = []
        dirty = false
        docVersion += 1
    }

    func reload() { switchProfile(activeProfile) }

    @discardableResult
    func newProfile(_ name: String) -> Bool {
        guard ProfileStore.isValidName(name) else { lastError = "Invalid profile name."; return false }
        let fresh = ProfileDocument.load(profile: name)
        do { try fresh.save() } catch { lastError = error.localizedDescription; return false }
        profiles = ProfileStore.listProfiles()
        switchProfile(name)
        return true
    }

    // MARK: Reads

    func rawString(_ path: String) -> String { doc.string(path) }
    func bool(_ path: String) -> Bool { doc.bool(path) }
    func isFilled(_ path: String) -> Bool { doc.isFilled(path) }
    func isRevealed(_ path: String) -> Bool { revealed.contains(path) }

    /// Value to show, honoring redaction tier + per-session reveal state.
    func display(_ path: String, _ sensitivity: Sensitivity) -> String {
        let raw = doc.string(path)
        if raw.isEmpty { return "" }
        if sensitivity == .low || revealed.contains(path) { return raw }
        return Redaction.mask(raw, sensitivity)
    }

    func filledCount(in section: String) -> Int {
        ProfileSchema.fields(in: section).filter { isFilled($0.path) }.count
    }

    // MARK: Documents

    func documents() -> [DocEntry] { DocumentManager.list(profile: activeProfile, doc: doc) }
    func documentCount() -> Int { doc.documentsMap.count }

    func attachDocument(_ url: URL, key: String? = nil) {
        do {
            try DocumentManager.attach(fileURL: url, key: key, profile: activeProfile, doc: doc)
            lastMessage = "Attached document."; lastError = nil; docVersion += 1
        } catch { lastError = error.localizedDescription }
    }

    func removeDocument(_ key: String) {
        do {
            try DocumentManager.remove(key: key, profile: activeProfile, doc: doc)
            lastMessage = "Removed document."; lastError = nil; docVersion += 1
        } catch { lastError = error.localizedDescription }
    }

    // MARK: Writes

    func setString(_ value: String, at path: String) {
        guard value != doc.string(path) else { return }
        doc.setString(value, at: path); dirty = true
    }

    func setBool(_ value: Bool, at path: String) {
        guard value != doc.bool(path) else { return }
        doc.setBool(value, at: path); dirty = true
    }

    func save() {
        do { try doc.save(); dirty = false; lastMessage = "Saved."; lastError = nil }
        catch { lastError = error.localizedDescription }
    }

    // MARK: Reveal / copy (high-sensitivity gated by Touch ID)

    func reveal(_ path: String, _ sensitivity: Sensitivity) async {
        if sensitivity == .high {
            guard await BiometricGate.confirm(reason: "Reveal “\(path)”") else { return }
        }
        revealed.insert(path)
    }

    func hide(_ path: String) { revealed.remove(path) }

    func copy(_ path: String, _ sensitivity: Sensitivity) async {
        let raw = doc.string(path)
        guard !raw.isEmpty else { return }
        if sensitivity == .high {
            guard await BiometricGate.confirm(reason: "Copy “\(path)”") else { return }
        }
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(raw, forType: .string)
        lastMessage = "Copied “\(path)”."
    }
}

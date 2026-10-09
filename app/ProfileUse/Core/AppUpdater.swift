// In-place updates for the menu bar app (same scheme as Pastyx and ChooseBrowser):
// download the notarized, stapled app archive from the newest public release,
// verify its checksum, Developer ID signature for this team and bundle id, Apple
// notarization, version and architecture, then swap the bundle atomically and
// relaunch. Nothing is replaced unless every check passes; Apple's code signature
// is the trust anchor, so no extra keys are involved.

import AppKit
import CryptoKit
import Foundation
import Security

// MARK: - Release feed

struct AppUpdateRelease: Equatable {
    let version: String
    let page: URL
    /// `ProfileUse-macos.tar.gz` (+ `.sha256`) — absent on releases made before
    /// in-place updates; those only offer the release page.
    let archive: URL?
    let checksum: URL?
    let size: Int64

    static let archiveName = "ProfileUse-macos.tar.gz"

    var canInstall: Bool { archive != nil && checksum != nil }

    private struct Payload: Decodable {
        struct Asset: Decodable {
            let name: String
            let url: String
            let size: Int64?
            enum CodingKeys: String, CodingKey { case name, url = "browser_download_url", size }
        }
        let tagName: String
        let htmlURL: URL
        let draft: Bool
        let prerelease: Bool
        let assets: [Asset]?
        enum CodingKeys: String, CodingKey {
            case tagName = "tag_name", htmlURL = "html_url", draft, prerelease, assets
        }
    }

    /// Newest stable `v<digits>` release in a `GET /repos/…/releases` list.
    static func newest(fromReleaseList data: Data) -> AppUpdateRelease? {
        guard let list = try? JSONDecoder().decode([Payload].self, from: data) else { return nil }
        let candidates = list.filter {
            !$0.draft && !$0.prerelease && $0.tagName.range(of: #"^v\d+(\.\d+)*$"#, options: .regularExpression) != nil
        }
        guard let best = candidates.max(by: {
            AppUpdater.isNewer(AppUpdater.normalized($1.tagName), than: AppUpdater.normalized($0.tagName))
        }) else { return nil }
        let assets = best.assets ?? []
        func https(_ name: String) -> URL? {
            assets.first { $0.name == name }.flatMap { URL(string: $0.url) }.flatMap { $0.scheme == "https" ? $0 : nil }
        }
        let pair = https(archiveName).flatMap { a in https(archiveName + ".sha256").map { (a, $0) } }
        return AppUpdateRelease(version: AppUpdater.normalized(best.tagName), page: best.htmlURL,
                                archive: pair?.0, checksum: pair?.1,
                                size: assets.first { $0.name == archiveName }?.size ?? 0)
    }
}

// MARK: - Errors

enum AppUpdateError: Error, Equatable {
    case network(String)
    case checksumMismatch
    case badArchive
    case signature(String)
    case notNotarized
    case wrongApp
    case wrongVersion(String)
    case wrongArchitecture
    case translocated
    case notWritable(String)
    case install(String)

    var message: String {
        switch self {
        case let .network(detail): return "The download didn’t finish (\(detail)). Check your connection and try again."
        case .checksumMismatch: return "The download was damaged or altered (checksum mismatch). Nothing was installed."
        case .badArchive: return "The download couldn’t be unpacked. Nothing was installed."
        case let .signature(detail): return "The update isn’t signed by the developer of Profile Use (\(detail)). Nothing was installed."
        case .notNotarized: return "The update isn’t notarized by Apple. Nothing was installed."
        case .wrongApp: return "The download isn’t Profile Use. Nothing was installed."
        case let .wrongVersion(found): return "The download is version \(found), not the one announced. Nothing was installed."
        case .wrongArchitecture: return "The update doesn’t run on this Mac’s processor. Nothing was installed."
        case .translocated: return "Move Profile Use to the Applications folder first, then update."
        case let .notWritable(folder): return "Profile Use can’t be replaced in “\(folder)” from this account. Run install-app.sh or ask an administrator."
        case let .install(detail): return "The update couldn’t be installed (\(detail)). Your current version is untouched."
        }
    }
}

// MARK: - Verification

enum AppUpdateVerifier {
    static let teamID = "6ZPXG4KVVS"

    static var machine: String {
        var info = utsname()
        uname(&info)
        return withUnsafePointer(to: &info.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
        }
    }

    static func sha256Hex(of file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func parseChecksum(_ text: String) -> String? {
        guard let token = text.split(whereSeparator: { $0 == " " || $0 == "\t" || $0.isNewline }).first else { return nil }
        let digest = token.lowercased()
        return digest.count == 64 && digest.allSatisfy(\.isHexDigit) ? digest : nil
    }

    static func verifyChecksum(of file: URL, against checksumText: String) throws {
        guard let expected = parseChecksum(checksumText), let actual = try? sha256Hex(of: file),
              expected == actual else { throw AppUpdateError.checksumMismatch }
    }

    static func requirement(bundleID: String, teamID: String = teamID) -> String {
        "identifier \"\(bundleID)\" and anchor apple generic"
            + " and certificate 1[field.1.2.840.113635.100.6.2.6] exists"
            + " and certificate leaf[field.1.2.840.113635.100.6.1.13] exists"
            + " and certificate leaf[subject.OU] = \"\(teamID)\""
    }

    private static func check(_ app: URL, requirement text: String) -> OSStatus {
        var code: SecStaticCode?
        var status = SecStaticCodeCreateWithPath(app as CFURL, [], &code)
        guard status == errSecSuccess, let code else { return status }
        var requirement: SecRequirement?
        status = SecRequirementCreateWithString(text as CFString, [], &requirement)
        guard status == errSecSuccess, let requirement else { return status }
        let flags = SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckAllArchitectures | kSecCSCheckNestedCode)
        return SecStaticCodeCheckValidity(code, flags, requirement)
    }

    static func verifySignature(of app: URL, bundleID: String) throws {
        let developerID = requirement(bundleID: bundleID)
        let status = check(app, requirement: developerID)
        guard status == errSecSuccess else {
            throw AppUpdateError.signature((SecCopyErrorMessageString(status, nil) as String?) ?? "OSStatus \(status)")
        }
        guard check(app, requirement: developerID + " and notarized") == errSecSuccess else {
            throw AppUpdateError.notNotarized
        }
    }

    static func verifyBundle(_ app: URL, bundleID: String, expectedVersion: String, currentVersion: String) throws {
        guard let bundle = Bundle(url: app), bundle.bundleIdentifier == bundleID else { throw AppUpdateError.wrongApp }
        let version = (bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? ""
        guard version == expectedVersion, AppUpdater.isNewer(version, than: currentVersion) else {
            throw AppUpdateError.wrongVersion(version.isEmpty ? "?" : version)
        }
        let wanted = machine == "arm64" ? NSBundleExecutableArchitectureARM64 : NSBundleExecutableArchitectureX86_64
        guard (bundle.executableArchitectures ?? []).contains(NSNumber(value: wanted)) else {
            throw AppUpdateError.wrongArchitecture
        }
    }

    static func verifyDestination(_ app: URL) throws {
        if app.path.contains("/AppTranslocation/") { throw AppUpdateError.translocated }
        let folder = app.deletingLastPathComponent()
        guard FileManager.default.isWritableFile(atPath: folder.path),
              FileManager.default.isWritableFile(atPath: app.path) else { throw AppUpdateError.notWritable(folder.path) }
    }
}

// MARK: - Installer

enum AppUpdater {
    static let feedURL = URL(string: "https://api.github.com/repos/leeguooooo/profile-use/releases?per_page=30")!

    static func fetchNewest(session: URLSession = .shared) async throws -> AppUpdateRelease? {
        var request = URLRequest(url: feedURL, timeoutInterval: 15)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("ProfileUse", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw AppUpdateError.network("HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)")
        }
        return AppUpdateRelease.newest(fromReleaseList: data)
    }

    static func install(_ release: AppUpdateRelease, currentVersion: String, bundleID: String, destination: URL,
                        progress: @escaping @MainActor (Double) -> Void) async throws {
        guard let archiveURL = release.archive, let checksumURL = release.checksum else { throw AppUpdateError.badArchive }
        try AppUpdateVerifier.verifyDestination(destination)
        let session = URLSession(configuration: .ephemeral)
        let work = FileManager.default.temporaryDirectory.appendingPathComponent("profileuse-update-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: work) }

        let archive = work.appendingPathComponent("update.tar.gz")
        try await download(archiveURL, to: archive, expectedSize: release.size, session: session, progress: progress)
        let checksumFile = work.appendingPathComponent("update.sha256")
        try await download(checksumURL, to: checksumFile, expectedSize: 0, session: session) { _ in }
        let checksumText = (try? String(contentsOf: checksumFile, encoding: .utf8)) ?? ""

        let staged = try await Task.detached(priority: .userInitiated) {
            try AppUpdateVerifier.verifyChecksum(of: archive, against: checksumText)
            let app = try unpack(archive, near: destination)
            do {
                try AppUpdateVerifier.verifyBundle(app, bundleID: bundleID, expectedVersion: release.version, currentVersion: currentVersion)
                try AppUpdateVerifier.verifySignature(of: app, bundleID: bundleID)
            } catch {
                try? FileManager.default.removeItem(at: app.deletingLastPathComponent())
                throw error
            }
            return app
        }.value
        try swap(staged, into: destination)
    }

    private static func download(_ url: URL, to file: URL, expectedSize: Int64, session: URLSession,
                                 progress: @escaping @MainActor (Double) -> Void) async throws {
        do {
            let (bytes, response) = try await session.bytes(from: url)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                throw AppUpdateError.network("HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)")
            }
            let total = expectedSize > 0 ? expectedSize : response.expectedContentLength
            FileManager.default.createFile(atPath: file.path, contents: nil)
            let handle = try FileHandle(forWritingTo: file)
            defer { try? handle.close() }
            var buffer = Data()
            buffer.reserveCapacity(1 << 16)
            var received: Int64 = 0
            for try await byte in bytes {
                buffer.append(byte)
                if buffer.count >= 1 << 16 {
                    try handle.write(contentsOf: buffer)
                    received += Int64(buffer.count)
                    buffer.removeAll(keepingCapacity: true)
                    if total > 0 { await progress(min(1, Double(received) / Double(total))) }
                }
            }
            try handle.write(contentsOf: buffer)
            await progress(1)
        } catch let error as AppUpdateError {
            throw error
        } catch {
            throw AppUpdateError.network(error.localizedDescription)
        }
    }

    static func unpack(_ archive: URL, near destination: URL) throws -> URL {
        let fm = FileManager.default
        let scratch: URL
        do {
            scratch = try fm.url(for: .itemReplacementDirectory, in: .userDomainMask, appropriateFor: destination, create: true)
        } catch {
            throw AppUpdateError.notWritable(destination.deletingLastPathComponent().path)
        }
        let tar = Process()
        tar.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
        tar.arguments = ["-xzf", archive.path, "-C", scratch.path]
        tar.standardOutput = FileHandle.nullDevice
        tar.standardError = FileHandle.nullDevice
        do {
            try tar.run()
            tar.waitUntilExit()
        } catch {
            try? fm.removeItem(at: scratch)
            throw AppUpdateError.badArchive
        }
        let apps = ((try? fm.contentsOfDirectory(at: scratch, includingPropertiesForKeys: nil)) ?? []).filter { $0.pathExtension == "app" }
        guard tar.terminationStatus == 0, apps.count == 1, let app = apps.first else {
            try? fm.removeItem(at: scratch)
            throw AppUpdateError.badArchive
        }
        return app
    }

    static func swap(_ staged: URL, into destination: URL) throws {
        let fm = FileManager.default
        do {
            _ = try fm.replaceItemAt(destination, withItemAt: staged, backupItemName: nil, options: [.usingNewMetadataOnly])
            try? fm.removeItem(at: staged.deletingLastPathComponent())
        } catch {
            try? fm.removeItem(at: staged.deletingLastPathComponent())
            let ns = error as NSError
            if ns.domain == NSCocoaErrorDomain, ns.code == NSFileWriteNoPermissionError || ns.code == NSFileWriteVolumeReadOnlyError {
                throw AppUpdateError.notWritable(destination.deletingLastPathComponent().path)
            }
            throw AppUpdateError.install(error.localizedDescription)
        }
    }

    @MainActor
    static func relaunch(_ app: URL) {
        let pid = ProcessInfo.processInfo.processIdentifier
        let shell = Process()
        shell.executableURL = URL(fileURLWithPath: "/bin/sh")
        shell.arguments = ["-c", "while /bin/kill -0 \(pid) 2>/dev/null; do /bin/sleep 0.1; done; /usr/bin/open \"$0\"", app.path]
        try? shell.run()
        NSApp.terminate(nil)
    }

    static func normalized(_ tag: String) -> String {
        tag.hasPrefix("v") || tag.hasPrefix("V") ? String(tag.dropFirst()) : tag
    }

    static func isNewer(_ candidate: String, than current: String) -> Bool {
        func parts(_ v: String) -> (numbers: [Int], pre: Bool) {
            let split = v.split(separator: "-", maxSplits: 1)
            return (split.first.map { $0.split(separator: ".").map { Int($0) ?? 0 } } ?? [], split.count > 1)
        }
        let a = parts(candidate), b = parts(current)
        for i in 0 ..< max(a.numbers.count, b.numbers.count) {
            let x = i < a.numbers.count ? a.numbers[i] : 0
            let y = i < b.numbers.count ? b.numbers[i] : 0
            if x != y { return x > y }
        }
        return !a.pre && b.pre
    }
}

// MARK: - Scheduling + UI state

/// Checks at launch, hourly and after wake (a real check at most once a day),
/// offers each new version once, and installs on request.
@MainActor
final class UpdateController: ObservableObject {
    enum State: Equatable {
        case idle, checking, upToDate
        case available(AppUpdateRelease)
        case installing(version: String, progress: Double)
        case failed(String)
    }

    @Published private(set) var state: State = .idle

    let currentVersion = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0"
    private let defaults = UserDefaults.standard
    private static let lastCheckKey = "update.lastCheckAt"
    private static let ignoredKey = "update.ignoredVersion"
    private static let interval: TimeInterval = 24 * 60 * 60
    private var timer: Timer?
    private var wakeObserver: NSObjectProtocol?

    func startPeriodicChecks() {
        checkIfDue()
        timer?.invalidate()
        let t = Timer(timeInterval: 60 * 60, repeats: true) { [weak self] _ in MainActor.assumeIsolated { self?.checkIfDue() } }
        t.tolerance = 5 * 60
        RunLoop.main.add(t, forMode: .common)
        timer = t
        if wakeObserver == nil {
            wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
                forName: NSWorkspace.didWakeNotification, object: nil, queue: .main
            ) { [weak self] _ in MainActor.assumeIsolated { self?.checkIfDue() } }
        }
    }

    func isDue(now: Date = Date()) -> Bool {
        now.timeIntervalSince1970 - defaults.double(forKey: Self.lastCheckKey) >= Self.interval
    }

    func checkIfDue() {
        guard isDue() else { return }
        Task { await check(userInitiated: false) }
    }

    func check(userInitiated: Bool) async {
        if case .checking = state { return }
        if case .installing = state { return }
        let previous = state
        state = .checking
        defaults.set(Date().timeIntervalSince1970, forKey: Self.lastCheckKey)
        do {
            guard let release = try await AppUpdater.fetchNewest(), AppUpdater.isNewer(release.version, than: currentVersion) else {
                state = .upToDate
                return
            }
            state = .available(release)
            if !userInitiated, defaults.string(forKey: Self.ignoredKey) != release.version {
                offer(release)
            }
        } catch {
            state = userInitiated ? .failed((error as? AppUpdateError)?.message ?? error.localizedDescription) : previous
        }
    }

    /// One alert per new version found by an automatic check.
    private func offer(_ release: AppUpdateRelease) {
        let alert = NSAlert()
        alert.messageText = "Profile Use \(release.version) is available"
        alert.informativeText = "You have \(currentVersion)."
        alert.addButton(withTitle: release.canInstall ? "Install and Relaunch" : "Open Release Page")
        alert.addButton(withTitle: "Later")
        alert.addButton(withTitle: "Skip This Version")
        NSApp.activate()
        switch alert.runModal() {
        case .alertFirstButtonReturn:
            if release.canInstall { install() } else { NSWorkspace.shared.open(release.page) }
        case .alertThirdButtonReturn: defaults.set(release.version, forKey: Self.ignoredKey)
        default: break
        }
    }

    func install() {
        guard case let .available(release) = state else { return }
        guard release.canInstall else {
            NSWorkspace.shared.open(release.page)
            return
        }
        state = .installing(version: release.version, progress: 0)
        let destination = Bundle.main.bundleURL
        let bundleID = Bundle.main.bundleIdentifier ?? "com.profileuse.app"
        Task {
            do {
                try await AppUpdater.install(release, currentVersion: currentVersion, bundleID: bundleID, destination: destination) { [weak self] p in
                    self?.state = .installing(version: release.version, progress: p)
                }
                AppUpdater.relaunch(destination)
            } catch {
                NSLog("[profile-use] update failed: \(error)")
                state = .failed((error as? AppUpdateError)?.message ?? AppUpdateError.install(error.localizedDescription).message)
            }
        }
    }
}

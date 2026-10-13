import Foundation

@main
struct ProfileDocumentChecks {
    static func main() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        setenv("PROFILE_USE_DIR", directory.path, 1)
        let path = ProfileStore.fileURL(for: "fixture")
        let data = Data(#"{"payment":{"card":{"number":{"$vault":{"item":"11111111-1111-4111-8111-111111111111","field":"number"}}}},"contact":{"email":"fixture@example.invalid"}}"#.utf8)
        try data.write(to: path)
        let document = ProfileDocument.load(profile: "fixture")
        precondition(document.isVaultReference("payment.card.number"))
        precondition(document.isFilled("payment.card.number"))
        document.setString("accidental replacement", at: "payment.card.number")
        precondition(document.isVaultReference("payment.card.number"))
        document.setString("changed@example.invalid", at: "contact.email")
        try document.save()
        precondition(ProfileDocument.load(profile: "fixture").isVaultReference("payment.card.number"))
        try Data(#"{"external":"newer edit"}"#.utf8).write(to: path)
        do {
            try document.save()
            fatalError("Stale editor overwrote external changes")
        } catch {
            let current = try Data(contentsOf: path)
            precondition(current == Data(#"{"external":"newer edit"}"#.utf8))
        }
        let fresh = ProfileDocument.load(profile: "new-profile")
        fresh.setString("New", at: "identity.given_name")
        try fresh.save()
        precondition(ProfileDocument.load(profile: "new-profile").string("identity.given_name") == "New")
        print("ProfileDocument: reference preservation, stale-save rejection and new-profile save passed")
    }
}

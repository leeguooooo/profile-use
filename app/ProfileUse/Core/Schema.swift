import Foundation

/// Per-field privacy tier — drives both display redaction and the unlock gate.
enum Sensitivity: String, Comparable {
    case low, medium, high
    private var rank: Int { self == .low ? 0 : (self == .medium ? 1 : 2) }
    static func < (a: Sensitivity, b: Sensitivity) -> Bool { a.rank < b.rank }
}

/// What control renders a field.
enum FieldKind { case text, date, bool }

/// One editable leaf, derived from `profile-schema.json` + `profile-template.json`.
struct FieldDescriptor: Identifiable {
    let path: String          // dot-path, e.g. "payment.card.number"
    let section: String       // schema-order section key
    let kind: FieldKind
    let sensitivity: Sensitivity
    var id: String { path }
    var leaf: String { path.split(separator: ".").last.map(String.init) ?? path }
}

enum ProfileSchema {
    /// Sections in schema order, with a display title + SF Symbol.
    static let sections: [(key: String, title: String, symbol: String)] = [
        ("identity", "Identity", "person.text.rectangle"),
        ("contact", "Contact", "envelope"),
        ("address", "Address", "house"),
        ("payment", "Payment", "creditcard"),
        ("bank", "Bank", "building.columns"),
        ("government_id", "Government ID", "person.badge.shield.checkmark"),
        ("tax", "Tax", "doc.text"),
        ("preferences", "Preferences", "slider.horizontal.3"),
        ("misc", "Other", "ellipsis.circle"),
    ]

    /// Section roots whose every descendant leaf inherits HIGH.
    static let highSections: Set<String> = ["payment", "bank", "government_id", "tax"]

    /// Segment-aware prefix match so "tax" does not match "taxonomy".
    static func sensitivity(for path: String) -> Sensitivity {
        if let d = descriptorsByPath[path] { return d.sensitivity }
        for root in highSections where path == root || path.hasPrefix("\(root).") { return .high }
        return .medium
    }

    static let descriptorsByPath: [String: FieldDescriptor] = {
        Dictionary(uniqueKeysWithValues: all.map { ($0.path, $0) })
    }()

    static func fields(in section: String) -> [FieldDescriptor] {
        all.filter { $0.section == section }
    }

    /// The full, schema-ordered descriptor table.
    static let all: [FieldDescriptor] = {
        func f(_ path: String, _ section: String, _ kind: FieldKind, _ s: Sensitivity) -> FieldDescriptor {
            FieldDescriptor(path: path, section: section, kind: kind, sensitivity: s)
        }
        return [
            // identity
            f("identity.full_name", "identity", .text, .medium),
            f("identity.family_name", "identity", .text, .medium),
            f("identity.given_name", "identity", .text, .medium),
            f("identity.middle_name", "identity", .text, .medium),
            f("identity.preferred_name", "identity", .text, .low),
            f("identity.birthdate", "identity", .date, .high),
            f("identity.gender", "identity", .text, .high),
            // contact
            f("contact.email", "contact", .text, .medium),
            f("contact.phone_country_code", "contact", .text, .medium),
            f("contact.phone", "contact", .text, .medium),
            f("contact.alternate_email", "contact", .text, .medium),
            // address
            f("address.country", "address", .text, .medium),
            f("address.region", "address", .text, .medium),
            f("address.city", "address", .text, .medium),
            f("address.ward_or_district", "address", .text, .medium),
            f("address.line1", "address", .text, .high),
            f("address.line2", "address", .text, .high),
            f("address.postal_code", "address", .text, .medium),
            f("address.jp.prefecture", "address", .text, .medium),
            f("address.jp.city", "address", .text, .medium),
            f("address.jp.banchi", "address", .text, .high),
            f("address.jp.building", "address", .text, .high),
            f("address.jp.postal_code_hyphenated", "address", .text, .medium),
            // payment (section HIGH)
            f("payment.card.holder_name", "payment", .text, .high),
            f("payment.card.number", "payment", .text, .high),
            f("payment.card.expiry_month", "payment", .text, .high),
            f("payment.card.expiry_year", "payment", .text, .high),
            f("payment.card.cvv", "payment", .text, .high),
            f("payment.card.billing_address_same_as_profile", "payment", .bool, .high),
            // bank (section HIGH)
            f("bank.country", "bank", .text, .high),
            f("bank.bank_name", "bank", .text, .high),
            f("bank.branch_name", "bank", .text, .high),
            f("bank.account_type", "bank", .text, .high),
            f("bank.account_number", "bank", .text, .high),
            f("bank.routing_number", "bank", .text, .high),
            f("bank.iban", "bank", .text, .high),
            f("bank.swift", "bank", .text, .high),
            f("bank.holder_name", "bank", .text, .high),
            // government_id (section HIGH)
            f("government_id.country", "government_id", .text, .high),
            f("government_id.type", "government_id", .text, .high),
            f("government_id.number", "government_id", .text, .high),
            f("government_id.expiry", "government_id", .text, .high),
            // tax (section HIGH)
            f("tax.country", "tax", .text, .high),
            f("tax.tax_id", "tax", .text, .high),
            // preferences
            f("preferences.locale", "preferences", .text, .low),
            f("preferences.currency", "preferences", .text, .low),
            f("preferences.marketing_opt_in", "preferences", .bool, .low),
            // root scalars
            f("notes", "misc", .text, .medium),
        ]
    }()
}

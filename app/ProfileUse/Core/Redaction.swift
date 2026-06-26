import Foundation

/// Display masking that mirrors the skill's redaction-by-default rule.
enum Redaction {
    /// `low` shows plainly; `medium` shows an orienting partial; `high` shows a
    /// fixed, NON length-revealing mask until explicitly revealed.
    static func mask(_ value: String, _ sensitivity: Sensitivity) -> String {
        guard !value.isEmpty else { return "" }
        switch sensitivity {
        case .low:
            return value
        case .medium:
            if let at = value.firstIndex(of: "@") {
                let name = value[value.startIndex..<at]
                let domain = value[value.index(after: at)...]
                return "\(name.prefix(1))***@\(domain)"
            }
            if value.count <= 4 { return String(repeating: "•", count: value.count) }
            return String(repeating: "•", count: value.count - 2) + value.suffix(2)
        case .high:
            return "••••••"
        }
    }
}

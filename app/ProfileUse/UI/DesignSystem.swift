import SwiftUI

/// Shared visual language, matched to the ChooseBrowser / cookie-use apps
/// (macOS 26 Liquid Glass, accent-driven, restrained). Radius scale 22/14/8/4.
enum DS {
    static let panelRadius: CGFloat = 22
    static let cardRadius: CGFloat = 14
    static let rowRadius: CGFloat = 8
}

extension View {
    /// Accent-tinted interactive glass for the active/selected element only.
    @ViewBuilder
    func selectionGlass(_ isActive: Bool) -> some View {
        if isActive {
            glassEffect(.regular.tint(.accentColor).interactive(),
                        in: .rect(cornerRadius: DS.rowRadius, style: .continuous))
        } else {
            self
        }
    }

    /// A grouped material card with a hairline tinted border.
    func infoCard(border: Color = .secondary, radius: CGFloat = DS.cardRadius) -> some View {
        padding(16)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous)
                .strokeBorder(border.opacity(0.25), lineWidth: 1))
    }
}

extension Sensitivity {
    var color: Color {
        switch self {
        case .low: return .secondary
        case .medium: return .blue
        case .high: return .orange
        }
    }

    var symbol: String {
        switch self {
        case .low: return "lock.open"
        case .medium: return "lock"
        case .high: return "lock.shield"
        }
    }
}

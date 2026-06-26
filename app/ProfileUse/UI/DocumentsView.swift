import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The "Documents" section: image attachments (ID, residence card, bank card)
/// stored next to the profile at mode 0600. High sensitivity — never auto-uploaded.
struct DocumentsView: View {
    @ObservedObject var model: ProfileModel
    @State private var removeKey: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Documents").font(.title2.weight(.semibold))
                    Spacer()
                    Button { addDocument() } label: { Label("Add document…", systemImage: "plus") }
                        .buttonStyle(.borderedProminent)
                }
                Label("Stored next to your profile (mode 600). High sensitivity — never auto-uploaded or copied elsewhere.",
                      systemImage: "lock.shield")
                    .font(.caption).foregroundStyle(.secondary)

                let docs = model.documents()
                if docs.isEmpty {
                    ContentUnavailableView("No documents", systemImage: "doc.on.doc",
                                           description: Text("Attach an ID, residence card, or bank card image."))
                        .frame(height: 240)
                } else {
                    ForEach(docs) { entry in row(entry) }
                }
                Spacer(minLength: 0)
            }
            .padding(24)
        }
        .navigationTitle("Documents")
        .confirmationDialog("Remove this document? The file is deleted.",
                            isPresented: Binding(get: { removeKey != nil }, set: { if !$0 { removeKey = nil } }),
                            titleVisibility: .visible) {
            Button("Remove", role: .destructive) { if let k = removeKey { model.removeDocument(k) }; removeKey = nil }
            Button("Cancel", role: .cancel) { removeKey = nil }
        }
    }

    private func row(_ entry: DocEntry) -> some View {
        HStack(spacing: 12) {
            thumbnail(entry)
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.key).font(.headline)
                Text(subtitle(entry)).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if entry.exists {
                Button { NSWorkspace.shared.activateFileViewerSelecting([entry.absolutePath]) } label: {
                    Image(systemName: "magnifyingglass")
                }
                .buttonStyle(.borderless).help("Reveal in Finder")
            }
            Button(role: .destructive) { removeKey = entry.key } label: { Image(systemName: "trash") }
                .buttonStyle(.borderless).foregroundStyle(.red)
        }
        .infoCard(border: .orange)
    }

    @ViewBuilder
    private func thumbnail(_ entry: DocEntry) -> some View {
        if entry.exists, let image = NSImage(contentsOf: entry.absolutePath) {
            Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: DS.rowRadius, style: .continuous))
        } else {
            RoundedRectangle(cornerRadius: DS.rowRadius, style: .continuous)
                .fill(Color.primary.opacity(0.06))
                .frame(width: 56, height: 56)
                .overlay(Image(systemName: entry.exists ? "doc" : "exclamationmark.triangle").foregroundStyle(.secondary))
        }
    }

    private func subtitle(_ entry: DocEntry) -> String {
        var parts: [String] = [entry.fileName]
        if !entry.exists { parts.append("missing") }
        else if let bytes = entry.sizeBytes { parts.append(ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)) }
        if let added = entry.added { parts.append(added.prefix(10).description) }
        return parts.joined(separator: " · ")
    }

    private func addDocument() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [.image, .pdf]
        if panel.runModal() == .OK, let url = panel.url {
            model.attachDocument(url)
        }
    }
}

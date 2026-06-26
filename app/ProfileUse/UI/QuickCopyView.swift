import SwiftUI

/// Menu-bar dropdown: fast Touch-ID-gated copy of a profile value while filling
/// a form by hand. High-sensitivity copies prompt; nothing is auto-revealed.
struct QuickCopyView: View {
    @ObservedObject var model: ProfileModel
    var onOpenEditor: () -> Void
    @State private var query = ""

    private var filled: [FieldDescriptor] {
        ProfileSchema.all.filter { model.isFilled($0.path) }
            .filter { query.isEmpty || $0.path.lowercased().contains(query.lowercased()) }
    }

    var body: some View {
        GlassEffectContainer(spacing: 10) {
            VStack(spacing: 0) {
                header
                searchBar
                Divider().padding(.horizontal, 14)
                list
                Divider()
                footer
            }
            .frame(width: 332)
            .glassEffect(.regular, in: .rect(cornerRadius: DS.panelRadius))
        }
        .padding(8)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "person.crop.rectangle.stack").font(.title3).foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 1) {
                Text("profile-use").font(.headline)
                Text(model.activeProfile).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, 14).padding(.top, 14).padding(.bottom, 10)
    }

    private var searchBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Search fields…", text: $query).textFieldStyle(.plain)
        }
        .padding(8)
        .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: DS.rowRadius))
        .padding(.horizontal, 14).padding(.bottom, 8)
    }

    private var list: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 1) {
                if filled.isEmpty {
                    Text("No filled fields.").font(.callout).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 100)
                }
                ForEach(filled) { field in
                    Button { Task { await model.copy(field.path, field.sensitivity) } } label: {
                        HStack(spacing: 8) {
                            Image(systemName: field.sensitivity.symbol)
                                .font(.caption).foregroundStyle(field.sensitivity.color).frame(width: 16)
                            VStack(alignment: .leading, spacing: 0) {
                                Text(field.path).font(.callout)
                                Text(model.display(field.path, field.sensitivity))
                                    .font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                            }
                            Spacer()
                            Image(systemName: "doc.on.doc").font(.caption).foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .contentShape(.rect(cornerRadius: DS.rowRadius))
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 6)
                }
            }
            .padding(.vertical, 6)
        }
        .frame(height: 280)
    }

    private var footer: some View {
        HStack(spacing: 10) {
            Button(action: onOpenEditor) { Label("Open editor", systemImage: "square.and.pencil") }
            Spacer()
            Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }
                .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain).font(.callout)
        .padding(.horizontal, 14).padding(.vertical, 10)
    }
}

import SwiftUI

/// Main window: profile picker + section list on the left, a schema-driven,
/// privacy-aware field editor on the right.
struct ProfileEditorView: View {
    @ObservedObject var model: ProfileModel
    @State private var section: String = "identity"
    @State private var showNewProfile = false
    @State private var newProfileName = ""

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            SectionEditor(model: model, section: section)
                .id("\(model.activeProfile)-\(section)-\(model.docVersion)")
        }
        .frame(minWidth: 720, minHeight: 540)
        .toolbar {
            ToolbarItem(placement: .navigation) { profileMenu }
            ToolbarItem(placement: .primaryAction) {
                Button { model.save() } label: { Label("Save", systemImage: "tray.and.arrow.down") }
                    .disabled(!model.dirty)
            }
        }
        .safeAreaInset(edge: .bottom) { statusBar }
        .alert("New profile", isPresented: $showNewProfile) {
            TextField("name (letters, numbers, - _)", text: $newProfileName)
            Button("Cancel", role: .cancel) {}
            Button("Create") { if model.newProfile(newProfileName) { newProfileName = "" } }
        }
    }

    private var profileMenu: some View {
        Menu {
            ForEach(model.profiles, id: \.self) { p in
                Button { model.switchProfile(p) } label: {
                    Label(p, systemImage: p == model.activeProfile ? "checkmark" : "person.crop.circle")
                }
            }
            Divider()
            Button { showNewProfile = true } label: { Label("New profile…", systemImage: "plus") }
        } label: {
            Label(model.activeProfile, systemImage: "person.crop.circle")
        }
    }

    private var sidebar: some View {
        List(selection: $section) {
            ForEach(ProfileSchema.sections, id: \.key) { s in
                let count = model.filledCount(in: s.key)
                Label {
                    HStack {
                        Text(s.title)
                        Spacer()
                        if count > 0 {
                            Text("\(count)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }
                    }
                } icon: {
                    Image(systemName: s.symbol)
                }
                .tag(s.key)
            }
        }
        .frame(minWidth: 220)
    }

    @ViewBuilder
    private var statusBar: some View {
        if let err = model.lastError {
            label(err, "exclamationmark.triangle.fill", .orange)
        } else if model.dirty {
            label("Unsaved changes", "pencil.circle", .secondary)
        } else if let msg = model.lastMessage {
            label(msg, "checkmark.circle.fill", .green)
        }
    }

    private func label(_ text: String, _ symbol: String, _ color: Color) -> some View {
        Label(text, systemImage: symbol)
            .font(.caption).foregroundStyle(color)
            .padding(.horizontal, 14).padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial)
    }
}

/// Renders all fields of one section as privacy-aware rows.
struct SectionEditor: View {
    @ObservedObject var model: ProfileModel
    let section: String

    var body: some View {
        Form {
            ForEach(ProfileSchema.fields(in: section)) { field in
                FieldRow(model: model, field: field)
            }
        }
        .formStyle(.grouped)
        .navigationTitle(ProfileSchema.sections.first { $0.key == section }?.title ?? section)
    }
}

/// One field: a plain editor when low/revealed, a masked value with reveal/copy
/// when redacted. High-sensitivity reveal/copy is Touch-ID gated by the model.
struct FieldRow: View {
    @ObservedObject var model: ProfileModel
    let field: FieldDescriptor

    private var title: String {
        field.leaf.replacingOccurrences(of: "_", with: " ").capitalized
    }

    var body: some View {
        switch field.kind {
        case .bool:
            Toggle(title, isOn: Binding(get: { model.bool(field.path) },
                                        set: { model.setBool($0, at: field.path) }))
        default:
            LabeledContent(title) { valueControl }
        }
    }

    @ViewBuilder
    private var valueControl: some View {
        let revealed = field.sensitivity == .low || model.isRevealed(field.path)
        HStack(spacing: 6) {
            if revealed {
                TextField("", text: Binding(get: { model.rawString(field.path) },
                                            set: { model.setString($0, at: field.path) }))
                    .textFieldStyle(.roundedBorder)
                    .frame(minWidth: 180)
                if field.sensitivity != .low {
                    Button { model.hide(field.path) } label: { Image(systemName: "eye.slash") }
                        .buttonStyle(.borderless).foregroundStyle(.secondary)
                }
            } else if model.isFilled(field.path) {
                Text(model.display(field.path, field.sensitivity))
                    .foregroundStyle(.secondary)
                    .frame(minWidth: 120, alignment: .leading)
                Button { Task { await model.reveal(field.path, field.sensitivity) } } label: {
                    Image(systemName: field.sensitivity == .high ? "lock.shield" : "eye")
                }
                .buttonStyle(.borderless)
                Button { Task { await model.copy(field.path, field.sensitivity) } } label: {
                    Image(systemName: "doc.on.doc")
                }
                .buttonStyle(.borderless).foregroundStyle(.secondary)
            } else {
                TextField("—", text: Binding(get: { model.rawString(field.path) },
                                             set: { model.setString($0, at: field.path) }))
                    .textFieldStyle(.roundedBorder)
                    .frame(minWidth: 180)
            }
        }
    }
}

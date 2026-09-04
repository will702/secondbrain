import SwiftUI

/// Menu bar status card: at-a-glance health + quick actions.
struct MenuBarContent: View {
    @EnvironmentObject private var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "brain")
                    .foregroundStyle(Color.accentColor)
                Text("Second Brain")
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
            }

            Divider()

            StatusRow(label: "Services", online: state.phase == .ready)
            StatusRow(label: "Local AI", online: state.aiOnline)

            Divider()

            Button {
                NSWorkspace.shared.open(state.apiURL ?? URL(string: "http://127.0.0.1:1/")!)
            } label: {
                Label("Open Second Brain", systemImage: "macwindow")
            }
            Button {
                state.restart()
                NSApp.activate(ignoringOtherApps: true)
                NSApp.windows.first?.makeKeyAndOrderFront(nil)
            } label: {
                Label("Restart Services", systemImage: "arrow.clockwise")
            }
            Button {
                state.pendingPath = "/setup"
                NSApp.activate(ignoringOtherApps: true)
                NSApp.windows.first?.makeKeyAndOrderFront(nil)
            } label: {
                Label(state.aiOnline ? "AI Settings" : "Enable AI…", systemImage: "sparkles")
            }
            Button {
                NSWorkspace.shared.open(Paths.logs)
            } label: {
                Label("Reveal Logs", systemImage: "doc.text.magnifyingglass")
            }

            Divider()

            Button(role: .destructive) {
                NSApplication.shared.terminate(nil)
            } label: {
                Label("Quit Second Brain", systemImage: "power")
            }
            .keyboardShortcut("q")
        }
        .buttonStyle(.plain)
        .padding(12)
        .frame(width: 240)
    }
}

private struct StatusRow: View {
    let label: String
    let online: Bool

    var body: some View {
        HStack {
            Circle()
                .fill(online ? Color.green : Color.orange)
                .frame(width: 7, height: 7)
            Text(label)
                .font(.system(size: 12))
                .foregroundStyle(.primary)
            Spacer()
            Text(online ? "Running" : "Offline")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
    }
}

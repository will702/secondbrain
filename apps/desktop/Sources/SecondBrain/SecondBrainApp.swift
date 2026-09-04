import SwiftUI

@main
struct SecondBrainApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var state = AppState.shared

    var body: some Scene {
        WindowGroup("Second Brain") {
            RootView()
                .environmentObject(state)
                .frame(minWidth: 980, minHeight: 640)
                .onAppear { state.bootstrap() }
        }
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {} // single window; no File > New
            CommandGroup(after: .appInfo) {
                Button("Reveal Logs") { NSWorkspace.shared.open(Paths.logs) }
                Button("Reveal Data Folder") { NSWorkspace.shared.open(Paths.support) }
            }
        }

        MenuBarExtra {
            MenuBarContent()
                .environmentObject(state)
        } label: {
            Image(systemName: state.aiOnline ? "brain" : "brain.filled")
        }
        .menuBarExtraStyle(.window)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var signalSources: [DispatchSourceSignal] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Route raw SIGTERM/SIGINT (logout scripts, `kill`) through graceful
        // child shutdown. Calling NSApp.terminate from a signal callout
        // deadlocks AppKit's reply dance, so we stop children and exit(0).
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            source.setEventHandler {
                AppState.shared.shutdown { exit(0) }
            }
            source.resume()
            signalSources.append(source)
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        AppState.shared.shutdown {
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        // Dock click always brings the window back.
        if !hasVisibleWindows { sender.windows.first?.makeKeyAndOrderFront(self) }
        return true
    }
}

/// Switches between the launch experience, the main webview, and failure UI.
struct RootView: View {
    @EnvironmentObject private var state: AppState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            switch state.phase {
            case .idle, .launching:
                LaunchView()
                    .transition(reduceMotion ? .opacity : .opacity.combined(with: .scale(scale: 0.98)))
            case .ready:
                MainView(url: state.apiURL ?? URL(string: "http://127.0.0.1:1/")!)
                    .transition(reduceMotion ? .opacity : .opacity.combined(with: .scale(scale: 1.02)))
            case .failed(let message):
                FailureView(message: message)
                    .transition(.opacity)
            }
        }
        .animation(reduceMotion ? .easeInOut(duration: 0.2) : .spring(response: 0.4, dampingFraction: 1.0), value: state.phase)
    }
}

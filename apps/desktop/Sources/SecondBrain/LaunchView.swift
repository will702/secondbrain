import SwiftUI

/// First-run/launch experience: instant feedback, one stage at a time,
/// critically-damped motion (no bounce — nothing here carries momentum).
struct LaunchView: View {
    @EnvironmentObject private var state: AppState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            Spacer()
            glyph
                .padding(.bottom, 24)
            Text("Second Brain")
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(.primary)
            Text("Your personal operating system")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .padding(.top, 4)
                .padding(.bottom, 40)

            VStack(alignment: .leading, spacing: 14) {
                ForEach(LaunchStage.allCases) { stage in
                    StageRow(
                        title: stage.title,
                        stageState: state.stageStates[stage] ?? .pending
                    )
                    .transition(reduceMotion ? .opacity : .opacity.combined(with: .move(edge: .bottom)))
                    .animation(
                        reduceMotion ? .easeOut(duration: 0.15) : .spring(response: 0.35, dampingFraction: 1.0),
                        value: state.stageStates[stage] ?? .pending
                    )
                }
            }
            .frame(width: 280)
            .padding(.horizontal, 24)
            .padding(.vertical, 20)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14))

            Spacer()
            if !state.aiOnline {
                Text("AI features activate after first-time setup")
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
                    .padding(.bottom, 16)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(backgroundGradient)
    }

    private var glyph: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 18)
                .fill(
                    LinearGradient(
                        colors: [.accentColor.opacity(0.85), .accentColor.opacity(0.55)],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    )
                )
                .frame(width: 72, height: 72)
                .shadow(color: .black.opacity(0.25), radius: 12, y: 5)
            Image(systemName: "brain")
                .font(.system(size: 34, weight: .medium))
                .foregroundStyle(.white)
        }
    }

    private var backgroundGradient: some View {
        LinearGradient(
            colors: [Color(nsColor: .windowBackgroundColor), Color(nsColor: .underPageBackgroundColor)],
            startPoint: .top, endPoint: .bottom
        )
        .ignoresSafeArea()
    }
}

private struct StageRow: View {
    let title: String
    let stageState: StageState

    var body: some View {
        HStack(spacing: 12) {
            icon.frame(width: 20)
            Text(title)
                .font(.system(size: 13, weight: stageState == .active ? .medium : .regular))
                .foregroundStyle(stageState == .pending ? .secondary : .primary)
            Spacer()
            if stageState == .active {
                ProgressView()
                    .controlSize(.small)
            }
        }
        .opacity(stageState == .pending ? 0.55 : 1)
    }

    @ViewBuilder
    private var icon: some View {
        switch stageState {
        case .pending:
            Image(systemName: "circle")
                .font(.system(size: 12, weight: .regular))
                .foregroundStyle(.tertiary)
        case .active:
            Image(systemName: "circle.dotted")
                .font(.system(size: 12, weight: .regular))
                .foregroundStyle(Color.accentColor)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 13, weight: .regular))
                .foregroundStyle(.green)
        }
    }
}

struct FailureView: View {
    let message: String
    @EnvironmentObject private var state: AppState

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 36))
                .foregroundStyle(.orange)
            Text("Second Brain couldn't start")
                .font(.system(size: 20, weight: .semibold))
            Text(message)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            HStack(spacing: 12) {
                Button("Try Again") { state.restart() }
                    .keyboardShortcut(.defaultAction)
                Button("Reveal Logs") { NSWorkspace.shared.open(Paths.logs) }
                Button("Quit") { NSApplication.shared.terminate(nil) }
            }
            .padding(.top, 8)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

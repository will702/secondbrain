import Combine
import Foundation

enum LaunchStage: String, CaseIterable, Identifiable {
    case database
    case migrations
    case api

    var id: String { rawValue }

    var title: String {
        switch self {
        case .database: return "Starting database"
        case .migrations: return "Preparing your brain"
        case .api: return "Starting services"
        }
    }
}

enum StageState {
    case pending
    case active
    case done
}

enum AppPhase: Equatable {
    case idle
    case launching
    case ready
    case failed(String)
}

/// Owns the backend process and everything around it.
/// The backend itself supervises postgres (manage-db mode), so this is a
/// two-level chain: AppState → backend → postgres.
@MainActor
final class AppState: ObservableObject {
    static let shared = AppState()

    @Published var phase: AppPhase = .idle
    @Published var stageStates: [LaunchStage: StageState] = [
        .database: .pending, .migrations: .pending, .api: .pending,
    ]
    @Published var apiPort: UInt16 = 0
    @Published var aiOnline = false
    @Published var aiEnabled = false  // models present in ~/Library/.../models

    private var backend: Process?
    private var lockFD: Int32?
    private var aiTimer: Timer?
    private var launchDeadline: DispatchSourceTimer?
    private var quitting = false
    private var stdoutBuffer = ""

    var apiURL: URL? {
        apiPort == 0 ? nil : URL(string: "http://127.0.0.1:\(apiPort)/")
    }

    // MARK: - Lifecycle

    func bootstrap() {
        guard phase == .idle else { return }
        Paths.ensureDirectories()
        Secrets.ensureConfigEnv(at: Paths.configEnv)

        guard FileManager.default.isExecutableFile(atPath: Paths.backendBinary.path) else {
            phase = .failed("Packaging error: backend not found at \(Paths.backendBinary.path)")
            return
        }

        guard let fd = ProcessUtil.acquireInstanceLock(at: Paths.lockFile) else {
            phase = .failed("Second Brain is already running. Check the menu bar (brain icon) or your Dock.")
            return
        }
        lockFD = fd

        phase = .launching
        startBackend()
        startAIHealthPolling()
    }

    private func startBackend() {
        let port = ProcessUtil.pickFreePort()
        apiPort = port

        let proc = Process()
        proc.executableURL = Paths.backendBinary
        proc.currentDirectoryURL = Paths.support
        proc.arguments = ["--port", String(port)]
        proc.environment = backendEnvironment(port: port)

        let stdout = Pipe()
        proc.standardOutput = stdout
        proc.standardError = logHandle(for: Paths.backendLog, reuse: false)

        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let line = String(data: data, encoding: .utf8) else {
                if data.isEmpty { handle.readabilityHandler = nil }
                return
            }
            Task { @MainActor in self?.handleBackendOutput(line) }
        }

        proc.terminationHandler = { [weak self] process in
            Task { @MainActor in self?.handleBackendExit(code: process.terminationStatus) }
        }

        do {
            try proc.run()
            backend = proc
            armLaunchDeadline()
        } catch {
            phase = .failed("Could not start the backend: \(error.localizedDescription)")
        }
    }

    private func backendEnvironment(port: UInt16) -> [String: String] {
        // Keep tesseract (OCR) discoverable if the user has Homebrew.
        let path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        return [
            "PATH": path,
            "HOME": NSHomeDirectory(),
            "SECONDBRAIN_MANAGE_DB": "1",
            "SECONDBRAIN_POSTGRES_BIN": Paths.postgresBin.path,
            "SECONDBRAIN_PGDATA": Paths.postgresData.path,
            "SECONDBRAIN_PG_LOG": Paths.postgresLog.path,
            "SECONDBRAIN_ENV_FILE": Paths.configEnv.path,
            "WEB_DIST_DIR": Paths.webDist.path,
            "DATA_DIR": Paths.data.path,
            "LLM_BASE_URL": "http://127.0.0.1:8080/v1",
        ]
    }

    private func logHandle(for url: URL, reuse: Bool) -> FileHandle {
        let fm = FileManager.default
        if !fm.fileExists(atPath: url.path) {
            fm.createFile(atPath: url.path, contents: nil)
        }
        guard let handle = FileHandle(forWritingAtPath: url.path) else {
            return FileHandle.nullDevice
        }
        if !reuse {
            try? handle.truncate(atOffset: 0)
            _ = try? handle.seekToEnd()
        } else {
            _ = try? handle.seekToEnd()
        }
        return handle
    }

    // MARK: - Backend output / exit

    private func handleBackendOutput(_ output: String) {
        stdoutBuffer += output
        while let newline = stdoutBuffer.firstIndex(of: "\n") {
            let line = String(stdoutBuffer[..<newline])
            stdoutBuffer = String(stdoutBuffer[stdoutBuffer.index(after: newline)...])
            guard let data = line.data(using: .utf8),
                  let event = try? JSONDecoder().decode(StageEvent.self, from: data),
                  event.event == "stage"
            else { continue }

            switch (event.stage, event.status) {
            case ("database", "starting"):
                stageStates[.database] = .active
            case ("database", "ready"):
                stageStates[.database] = .done
                stageStates[.migrations] = .active
            case ("migrations", "done"):
                stageStates[.migrations] = .done
                stageStates[.api] = .active
            case ("api", "ready"):
                stageStates[.api] = .done
                if phase == .launching { phase = .ready }
                launchDeadline = nil
            default:
                break
            }
        }
    }

    private func handleBackendExit(code: Int32) {
        launchDeadline = nil
        guard !quitting else { return }
        if phase == .ready || phase == .launching {
            let hint = "The backend stopped unexpectedly (exit \(code)). Your data is safe."
            phase = .failed(hint)
        }
    }

    private func armLaunchDeadline() {
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        timer.schedule(deadline: .now() + 120)
        timer.setEventHandler { [weak self] in
            Task { @MainActor in
                guard let self, self.phase == .launching else { return }
                self.phase = .failed("Timed out waiting for the backend to start.")
                self.backend?.terminate()
            }
        }
        timer.resume()
        launchDeadline = timer
    }

    func restart() {
        backend?.terminate()
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) { group.leave() }

        stageStates = [.database: .pending, .migrations: .pending, .api: .pending]
        phase = .launching
        startBackend()
    }

    // MARK: - Shutdown

    /// SIGTERM the backend (it drains the API, then fast-stops postgres).
    func shutdown(completion: @escaping () -> Void) {
        quitting = true
        aiTimer?.invalidate()
        guard let backend, backend.isRunning else {
            completion()
            return
        }
        backend.terminate()
        DispatchQueue.global(qos: .userInitiated).async { [weak backend] in
            // Fast shutdown is normally <2s; allow generous headroom for WAL.
            let deadline = Date().addingTimeInterval(25)
            while Date() < deadline {
                if backend?.isRunning == false { break }
                Thread.sleep(forTimeInterval: 0.2)
            }
            if backend?.isRunning == true {
                backend?.interrupt()
                Thread.sleep(forTimeInterval: 3)
                if backend?.isRunning == true { kill(backend!.processIdentifier, SIGKILL) }
            }
            DispatchQueue.main.async { completion() }
        }
    }

    // MARK: - AI health

    private func startAIHealthPolling() {
        pollAI()
        let timer = Timer(timeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.pollAI() }
        }
        RunLoop.main.add(timer, forMode: .common)
        aiTimer = timer
    }

    private func pollAI() {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8080/health")!)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            let online = (response as? HTTPURLResponse)?.statusCode == 200
            Task { @MainActor in self?.aiOnline = online }
        }.resume()
    }
}

private struct StageEvent: Decodable {
    let event: String
    let stage: String
    let status: String
}

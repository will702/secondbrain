// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SecondBrain",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "SecondBrain", path: "Sources/SecondBrain")
    ]
)

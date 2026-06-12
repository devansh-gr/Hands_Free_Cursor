// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "bridge",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "bridge",
            path: "Sources/bridge",
            linkerSettings: [
                // Embed Info.plist into the binary so a bare CLI tool can
                // carry the NSMotionUsageDescription key required for the
                // headphone-motion permission prompt.
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Resources/Info.plist",
                ])
            ]
        )
    ]
)

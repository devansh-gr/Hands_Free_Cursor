// telekinesis-bridge — Stage 1 of the fusion pipeline.
//
// Reads AirPods head attitude via CMHeadphoneMotionManager and streams raw
// quaternions as JSON lines over UDP to the Python engine. Deliberately dumb:
// no math here. All geometry lives in the engine where it can be unit-tested.

import Foundation
import CoreMotion
import Network

let HOST: NWEndpoint.Host = "127.0.0.1"
let PORT: NWEndpoint.Port = 8077

func log(_ msg: String) {
    FileHandle.standardError.write(("bridge: " + msg + "\n").data(using: .utf8)!)
}

final class Bridge: NSObject, CMHeadphoneMotionManagerDelegate {
    private let motion = CMHeadphoneMotionManager()
    private let conn = NWConnection(host: HOST, port: PORT, using: .udp)
    private var sampleCount = 0

    func run() {
        guard motion.isDeviceMotionAvailable else {
            log("error: headphone motion unavailable. Are AirPods connected and in-ear?")
            exit(1)
        }
        motion.delegate = self
        conn.start(queue: .main)
        motion.startDeviceMotionUpdates(to: .main) { [weak self] sample, error in
            if let error {
                log("motion error: \(error.localizedDescription)")
                return
            }
            guard let self, let sample else { return }
            let q = sample.attitude.quaternion
            // sample.timestamp shares the mach_absolute_time base, so the
            // engine can compute one-way latency against CLOCK_UPTIME_RAW.
            let line = String(
                format: "{\"t\":%.6f,\"qw\":%.6f,\"qx\":%.6f,\"qy\":%.6f,\"qz\":%.6f}\n",
                sample.timestamp, q.w, q.x, q.y, q.z
            )
            self.conn.send(content: line.data(using: .utf8), completion: .idempotent)
            self.sampleCount += 1
            if self.sampleCount == 1 { log("first sample received — streaming") }
        }
        log("streaming headphone motion → udp://127.0.0.1:8077 (ctrl-c to stop)")
    }

    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        log("AirPods connected")
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        log("AirPods disconnected — cursor will freeze until they reconnect")
    }
}

let bridge = Bridge()
bridge.run()
RunLoop.main.run()

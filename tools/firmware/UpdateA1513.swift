import Foundation
import CoreFoundation
import CryptoKit
import IOKit.hid
import Darwin

// A1513 Main0241 OTA handler: 0x1bfd8; GET B2: 0x1bfb4.
// B0 C3BC begins and clears the persisted apply mask; B0 6272 resets one payload.
// B1 appends to a 256-byte buffer. Send the complete 128-byte header first.
// B2 00 verifies the complete signed payload and sets status A1 on success.
// B2 C3BC persists the apply mask after the firmware's battery check.
// B3 (no payload) requests deferred reset via 0xe1f4 -> 0xd15c -> 0x1badc.
// Boot0241 base=0, function 0x1c80 applies the mask. Bootloader is NOT updated.

func log(_ s: String) { print(s); fflush(stdout) }
enum Failure: Error { case stop(String) }
let oldRevision = "01004102200070033000070131001800B000410240001508"
let newRevision = "01005702200070033000200131001800B000410240001508"
struct Component {
    let name: String
    let bytes: [UInt8]
}
protocol Transport {
    func write(_ report: UInt8, _ payload: [UInt8]) throws
    func status() throws -> UInt8
}

func update(_ transport: Transport, _ components: [Component], phase: (String) throws -> Void) throws {
    guard components.count == 2, components[0].name == "main", components[1].name == "radio",
          components.allSatisfy({ $0.bytes.count >= 416 }) else { throw Failure.stop("invalid component plan") }
    guard try transport.status() == 0 else { throw Failure.stop("initial OTA status is not the observed zero baseline") }
    try phase("begin-pending")
    try transport.write(0xb0, [0xc3,0xbc])
    for component in components {
        try phase("reset-payload-\(component.name)")
        try transport.write(0xb0, [0x62,0x72])
        guard try transport.status() == 0 else { throw Failure.stop("payload status did not reset") }
        try phase("transfer-\(component.name)")
        var offset = 0
        var lastPercent = -10
        while offset < component.bytes.count {
            let end = min(offset + 128, component.bytes.count)
            // No retries: an uncertain B1 write must never be duplicated.
            try transport.write(0xb1, Array(component.bytes[offset..<end]))
            offset = end
            if offset % 2048 == 0 || offset == component.bytes.count {
                let status = try transport.status()
                guard status == 0 else { throw Failure.stop(String(format:"transfer status 0x%02x",status)) }
            }
            let percent = offset * 100 / component.bytes.count
            if percent >= lastPercent + 10 || offset == component.bytes.count {
                log("\(component.name): \(offset)/\(component.bytes.count) bytes (\(percent)%)")
                lastPercent = percent
            }
        }
        try phase("verify-\(component.name)")
        try transport.write(0xb2, [0])
        let status = try transport.status()
        guard status == 0xa1 else { throw Failure.stop(String(format:"signed payload verification failed: 0x%02x",status)) }
        log("\(component.name): device reports signed payload verification success (A1).")
    }
    // Only reached if BOTH complete signed files were accepted by the device.
    try phase("arm-pending")
    try transport.write(0xb2, [0xc3,0xbc])
    try phase("armed")
    try phase("reboot-pending")
    try transport.write(0xb3, [])
    try phase("reboot-request-acknowledged")
}

final class Simulation: Transport {
    var writes: [(UInt8,[UInt8])] = []
    var staged: [[UInt8]] = []
    var statusValue: UInt8 = 0
    var fault: String
    var statusReads = 0
    init(_ fault: String) { self.fault = fault }
    func write(_ report: UInt8, _ payload: [UInt8]) throws {
        writes.append((report,payload))
        if report == 0xb1 && (fault == "write" || (fault == "write-radio" && staged.count == 2)) {
            throw Failure.stop("injected transport failure")
        }
        if report == 0xb0 && payload == [0x62,0x72] { staged.append([]); statusValue = 0 }
        if report == 0xb1 { staged[staged.count-1] += payload }
        if report == 0xb2 && payload == [0] {
            statusValue = (fault == "signature" || (fault == "signature-radio" && staged.count == 2)) ? 0x70 : 0xa1
        }
        if fault == "arm" && report == 0xb2 && payload == [0xc3,0xbc] { throw Failure.stop("injected arm failure") }
    }
    func status() throws -> UInt8 {
        statusReads += 1
        if fault == "read" && statusReads >= 3 { throw Failure.stop("injected missing response") }
        return statusValue
    }
}

func selfTest() throws {
    let samples = [Component(name:"main",bytes:(0..<487).map { UInt8($0 % 251) }),
                   Component(name:"radio",bytes:(0..<539).map { UInt8($0 % 239) })]
    for fault in ["none","write","write-radio","signature","signature-radio","read","arm","journal","journal-after-arm"] {
        let simulator = Simulation(fault)
        var failed = false
        do {
            try update(simulator,samples) { phase in
                if fault == "journal" && phase == "arm-pending" { throw Failure.stop("journal unavailable") }
                if fault == "journal-after-arm" && phase == "armed" { throw Failure.stop("journal unavailable after arm") }
            }
        } catch { failed = true }
        let arm = simulator.writes.filter { $0.0 == 0xb2 && $0.1 == [0xc3,0xbc] }
        let reset = simulator.writes.filter { $0.0 == 0xb3 }
        if fault == "none" {
            guard !failed, simulator.staged == samples.map({$0.bytes}), arm.count == 1, reset.count == 1 else {
                throw Failure.stop("successful transfer simulation failed")
            }
        } else {
            guard failed, reset.isEmpty, (["arm","journal-after-arm"].contains(fault) ? arm.count == 1 : arm.isEmpty) else {
                throw Failure.stop("failure could reach activation: \(fault)")
            }
        }
        let dataWrites = simulator.writes.filter { $0.0 == 0xb1 }
        guard dataWrites.allSatisfy({ !$0.1.isEmpty && $0.1.count <= 128 }) else {
            throw Failure.stop("invalid transfer chunk")
        }
        if fault == "write" && dataWrites.count != 1 { throw Failure.stop("uncertain write was retried") }
    }
    log("PASS: exact payload transfer and failure gates (transport, signature, missing response, arm, journal). No device access.")
}

func property(_ device: IOHIDDevice, _ key: String) -> Int {
    (IOHIDDeviceGetProperty(device,key as CFString) as? NSNumber)?.intValue ?? -1
}
func revision(_ device: IOHIDDevice) -> String {
    (IOHIDDeviceGetProperty(device,"kBTFirmwareRevisionKey" as CFString) as? String ?? "").uppercased()
}
func makeManager() -> IOHIDManager {
    let manager = IOHIDManagerCreate(kCFAllocatorDefault,IOOptionBits(kIOHIDOptionsTypeNone))
    IOHIDManagerSetDeviceMatching(manager,[kIOHIDVendorIDKey as String:0x004c,kIOHIDProductIDKey as String:0x0266] as CFDictionary)
    return manager
}
func managementDevices(_ manager: IOHIDManager) -> [IOHIDDevice] {
    return ((IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice>) ?? []).filter {
        property($0,"bInterfaceNumber") == 0 && property($0,kIOHIDPrimaryUsagePageKey as String) == 0xff00 && property($0,kIOHIDPrimaryUsageKey as String) == 11
    }
}

final class Native: Transport {
    let device: IOHIDDevice
    init(_ device: IOHIDDevice) { self.device = device }
    func get(_ report: UInt8) throws -> UInt8 {
        guard report == 0xa0 || report == 0xb2 else { throw Failure.stop("GET report blocked") }
        var bytes = [UInt8](repeating:0,count:209)
        bytes[0] = report
        var length: CFIndex = bytes.count
        let result = bytes.withUnsafeMutableBufferPointer {
            IOHIDDeviceGetReport(device,kIOHIDReportTypeFeature,CFIndex(report),$0.baseAddress!,&length)
        }
        guard result == kIOReturnSuccess, length == 2, bytes[0] == report else {
            throw Failure.stop(String(format:"GET %02x failed: 0x%08x, length=%ld",report,UInt32(bitPattern:result),length))
        }
        return bytes[1]
    }
    func status() throws -> UInt8 { try get(0xb2) }
    func write(_ report: UInt8, _ payload: [UInt8]) throws {
        let allowed = (report == 0xb0 && (payload == [0xc3,0xbc] || payload == [0x62,0x72])) ||
            (report == 0xb1 && (1...128).contains(payload.count)) ||
            (report == 0xb2 && (payload == [0] || payload == [0xc3,0xbc])) ||
            (report == 0xb3 && payload.isEmpty)
        guard allowed else { throw Failure.stop("SET report blocked") }
        let bytes = [report]+payload
        let result = bytes.withUnsafeBufferPointer {
            IOHIDDeviceSetReport(device,kIOHIDReportTypeFeature,CFIndex(report),$0.baseAddress!,bytes.count)
        }
        guard result == kIOReturnSuccess else {
            throw Failure.stop(String(format:"SET %02x failed: 0x%08x; no retry",report,UInt32(bitPattern:result)))
        }
        if report == 0xb1 { usleep(10_000) }
    }
}

func loadComponents(_ directory: String) throws -> [Component] {
    let specifications: [(String,Int,String)] = [
        ("main",166214,"a4287261b4376c3842e9a3cdd3e006623f2ad6135c5f35600fab6264e0c594ad"),
        ("radio",27988,"18b1bcc03df8e27b4f2389c615275d73c5b298d16a5f6f5d7c27fa28618b5aec")]
    return try specifications.map { name,size,hash in
        let data = try Data(contentsOf:URL(fileURLWithPath:directory).appendingPathComponent(name+".bin"))
        let digest = SHA256.hash(data:data).map { String(format:"%02x",$0) }.joined()
        guard data.count == size, digest == hash else { throw Failure.stop("component mismatch: \(name)") }
        return Component(name:name,bytes:Array(data))
    }
}

if CommandLine.arguments.contains("--self-test") {
    do { try selfTest(); exit(0) } catch { log("TEST FAILED: \(error)"); exit(1) }
}
guard CommandLine.arguments.count == 4, CommandLine.arguments[1] == "--apply" else {
    log("Usage: --self-test OR --apply PREPARED_COMPONENT_DIRECTORY JOURNAL_PATH"); exit(2)
}
var phaseName = "preflight"
var activationMayHaveBeenSent = false
let journalPath = CommandLine.arguments[3]
func record(_ phase: String) throws {
    phaseName = phase
    if phase == "arm-pending" { activationMayHaveBeenSent = true }
    let document: [String:Any] = ["phase":phase,"time":ISO8601DateFormatter().string(from:Date()),
                                "from":oldRevision,"to":newRevision,"bootloader_updated":false]
    try JSONSerialization.data(withJSONObject:document,options:[.prettyPrinted,.sortedKeys])
        .write(to:URL(fileURLWithPath:journalPath),options:.atomic)
    log("PHASE: \(phase)")
}
do {
    log("Updater effective UID: \(geteuid())")
    log("MODEL NOTICE: A1513 only (no white MENU ring). A1962 (white MENU ring) is NOT supported. Do not bypass model/version checks.")
    let components = try loadComponents(CommandLine.arguments[2])
    let manager = makeManager()
    defer { withExtendedLifetime(manager) {} }
    let devices = managementDevices(manager)
    guard devices.count == 1, let device = devices.first,
          property(device,kIOHIDMaxFeatureReportSizeKey as String) == 209 else {
        throw Failure.stop("exactly one A1513 management interface with feature size 209 is required; A1962 (white MENU ring) is not supported")
    }
    if revision(device) == newRevision {
        log("ALREADY CURRENT: Main0257/Radio0120/Boot0241. No firmware commands sent."); exit(0)
    }
    guard revision(device) == oldRevision else { throw Failure.stop("firmware is not the audited Main0241/Radio0107/Boot0241 combination") }
    let identity = IOHIDDeviceGetProperty(device,"PhysicalDeviceUniqueID" as CFString) as? String
    guard let identity, !identity.isEmpty else { throw Failure.stop("stable device identity unavailable") }
    let opened = IOHIDDeviceOpen(device,IOOptionBits(kIOHIDOptionsTypeNone))
    guard opened == kIOReturnSuccess else { throw Failure.stop(String(format:"HID open failed: 0x%08x",UInt32(bitPattern:opened))) }
    let native = Native(device)
    do {
        guard try native.get(0xa0) == 0 else { throw Failure.stop("sensor mode must be 0 before update") }
        try record("preflight-passed")
        log("EXPERIMENTAL FIRMWARE UPDATE: main 0241 -> 0257; radio 0107 -> 0120. Keep power and Bluetooth connected.")
        try update(native,components,phase:record)
    } catch {
        IOHIDDeviceClose(device,IOOptionBits(kIOHIDOptionsTypeNone))
        throw error
    }
    IOHIDDeviceClose(device,IOOptionBits(kIOHIDOptionsTypeNone))
    log("Reboot requested. Waiting up to 120 seconds for the same remote to report the new versions.")
    let deadline = Date().addingTimeInterval(120)
    var observed = ""
    while Date() < deadline {
        let refreshedManager = makeManager()
        defer { withExtendedLifetime(refreshedManager) {} }
        for candidate in managementDevices(refreshedManager) {
            guard (IOHIDDeviceGetProperty(candidate,"PhysicalDeviceUniqueID" as CFString) as? String) == identity else { continue }
            let value = revision(candidate)
            if value != observed { log("Reported firmware: \(value)"); observed = value }
            if value == newRevision {
                try record("new-version-reported")
                log("PASS: the same remote reports Main0257/Radio0120/Boot0241. Confirm normal operation separately.")
                exit(0)
            }
        }
        Thread.sleep(forTimeInterval:2)
    }
    try record("post-reboot-verification-unconfirmed")
    log("UPDATE RESULT UNCONFIRMED: no matching new firmware report within 120 seconds. Do not rerun the updater; retain this log.")
    exit(7)
} catch {
    log("STOP at \(phaseName): \(error)")
    log("No retry or automatic recovery was attempted. Do not rerun the updater; retain the log and journal.")
    if activationMayHaveBeenSent {
        log("Activation or reboot may already have occurred. The outcome must be checked before any further writes.")
    } else {
        log("This run did not send the activation or reboot command.")
    }
    exit(5)
}

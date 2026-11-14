import Foundation
import CoreBluetooth
import CoreFoundation
import IOKit.hid
import Darwin

let expected = "01005702200070033000200131001800B000410240001508"
func log(_ text: String) { print(text); fflush(stdout) }
func prop(_ d: IOHIDDevice,_ key: String) -> Int {
    (IOHIDDeviceGetProperty(d,key as CFString) as? NSNumber)?.intValue ?? -1
}
func version(_ d: IOHIDDevice) -> String {
    (IOHIDDeviceGetProperty(d,"kBTFirmwareRevisionKey" as CFString) as? String ?? "").uppercased()
}
var inputCounts: [String:Int] = [:]
var inputErrors = 0
let manager = IOHIDManagerCreate(kCFAllocatorDefault,IOOptionBits(kIOHIDOptionsTypeNone))
IOHIDManagerSetDeviceMatching(manager,[kIOHIDVendorIDKey as String:76,kIOHIDProductIDKey as String:614] as CFDictionary)
let devices = Array((IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice>) ?? [])
let identities = Set(devices.compactMap { IOHIDDeviceGetProperty($0,"PhysicalDeviceUniqueID" as CFString) as? String })
guard identities.count == 1, let identity = identities.first,
      let targetUUID = UUID(uuidString:identity), !devices.isEmpty else {
    log("UNCONFIRMED: exactly one connected A1513 identity is required."); exit(2)
}
let interfaces = devices.map { prop($0,"bInterfaceNumber") }.sorted()
log("Interfaces: \(interfaces)")
let registryOK = interfaces == Array(0...7) && devices.allSatisfy { version($0) == expected && prop($0,kIOHIDMaxFeatureReportSizeKey as String) == 209 }
log("Registry firmware/interface check: \(registryOK ? "PASS" : "MISMATCH")")
log("Registry firmware: \(Set(devices.map(version)).sorted())")
let management = devices.filter { prop($0,"bInterfaceNumber") == 0 && prop($0,kIOHIDPrimaryUsagePageKey as String) == 0xff00 && prop($0,kIOHIDPrimaryUsageKey as String) == 11 }
guard registryOK, management.count == 1 else { log("STOP: device differs from the updated remote."); exit(3) }
let device = management[0]
let opened = IOHIDDeviceOpen(device,IOOptionBits(kIOHIDOptionsTypeNone))
log(String(format:"Management open=0x%08x",UInt32(bitPattern:opened)))
var nativeSamples: [[String:Int]] = []
func queryNative() {
    guard opened == kIOReturnSuccess else { return }
    var sample: [String:Int] = [:]
    for selector: UInt8 in [0xa0,0xb2] {
        var buffer = [UInt8](repeating:0,count:209)
        buffer[0] = selector
        var length: CFIndex = buffer.count
        let result = buffer.withUnsafeMutableBufferPointer {
            IOHIDDeviceGetReport(device,kIOHIDReportTypeFeature,CFIndex(selector),$0.baseAddress!,&length)
        }
        let key = String(format:"%02x",selector)
        if result == kIOReturnSuccess && length == 2 && buffer[0] == selector {
            sample[key] = Int(buffer[1]); log(String(format:"GET %@=%02x",key,buffer[1]))
        } else { log(String(format:"GET %@ failed result=0x%08x length=%ld",key,UInt32(bitPattern:result),length)) }
    }
    nativeSamples.append(sample)
}
queryNative()

// Count events only; do not store raw HID reports, microphone data, or button contents.
IOHIDManagerRegisterInputValueCallback(manager,{ _,result,_,value in
    guard result == kIOReturnSuccess else { inputErrors += 1; return }
    let element = IOHIDValueGetElement(value)
    let sender = IOHIDElementGetDevice(element)
    let interface = prop(sender,"bInterfaceNumber")
    let key = String(format:"interface=%d report=%02x",interface,IOHIDElementGetReportID(element))
    inputCounts[key,default:0] += 1
},nil)
IOHIDManagerScheduleWithRunLoop(manager,CFRunLoopGetMain(),CFRunLoopMode.defaultMode.rawValue)
let inputOpen = IOHIDManagerOpen(manager,IOOptionBits(kIOHIDOptionsTypeNone))
log(String(format:"Passive input open=0x%08x",UInt32(bitPattern:inputOpen)))

final class BLE: NSObject,CBCentralManagerDelegate,CBPeripheralDelegate {
    let targetID: UUID
    var central: CBCentralManager!
    var remote: CBPeripheral?
    var firmware: [String] = []
    var values: [String:String] = [:]
    var errors: [String] = []
    var disconnects = 0
    init(targetID: UUID) { self.targetID = targetID; super.init(); central = CBCentralManager(delegate:self,queue:nil) }
    func centralManagerDidUpdateState(_ c:CBCentralManager) {
        log("Bluetooth state=\(c.state.rawValue) authorization=\(CBManager.authorization.rawValue)")
        guard c.state == .poweredOn, remote == nil else { return }
        guard let p = c.retrievePeripherals(withIdentifiers:[targetID]).first else {
            errors.append("known peripheral unavailable"); return
        }
        remote = p; p.delegate = self; c.connect(p,options:nil)
    }
    func centralManager(_ c:CBCentralManager,didConnect p:CBPeripheral) {
        log("BLE connected to the same remote; reading Device Information and Battery services.")
        p.discoverServices([CBUUID(string:"180A"),CBUUID(string:"180F")])
    }
    func centralManager(_ c:CBCentralManager,didFailToConnect p:CBPeripheral,error:Error?) { errors.append("connect: \(String(describing:error))") }
    func centralManager(_ c:CBCentralManager,didDisconnectPeripheral p:CBPeripheral,error:Error?) {
        disconnects += 1; errors.append("disconnect: \(String(describing:error))")
    }
    func peripheral(_ p:CBPeripheral,didDiscoverServices error:Error?) {
        if let error { errors.append("services: \(error)"); return }
        for s in p.services ?? [] {
            p.discoverCharacteristics([CBUUID(string:"2A26"),CBUUID(string:"2A27"),CBUUID(string:"2A50"),CBUUID(string:"2A19"),CBUUID(string:"2A1A")],for:s)
        }
    }
    func peripheral(_ p:CBPeripheral,didDiscoverCharacteristicsFor s:CBService,error:Error?) {
        if let error { errors.append("characteristics: \(error)"); return }
        for ch in s.characteristics ?? [] where ch.properties.contains(.read) { p.readValue(for:ch) }
    }
    func peripheral(_ p:CBPeripheral,didUpdateValueFor ch:CBCharacteristic,error:Error?) {
        let key = ch.uuid.uuidString
        if let error { errors.append("read \(key): \(error)"); return }
        guard let data = ch.value else { errors.append("empty \(key)"); return }
        values[key] = data.map { String(format:"%02x",$0) }.joined()
        if key == "2A26" {
            let text = (String(data:data,encoding:.utf8) ?? "").uppercased()
            firmware.append(text); log("Direct GATT firmware read \(firmware.count): \(text)")
            if firmware.count < 3 {
                DispatchQueue.main.asyncAfter(deadline:.now()+5) { [weak self] in
                    guard self?.remote?.state == .connected else { return }
                    p.readValue(for:ch)
                }
            }
        } else if key == "2A19", data.count == 1 { log("Battery: \(data[0])%") }
        else { log("GATT \(key): \(values[key] ?? "")") }
    }
}
let ble = BLE(targetID:targetUUID)
log("Observe for 40 seconds. Swipe the touch surface and press ordinary buttons individually; do not hold pairing/reset combinations.")
RunLoop.main.run(until:Date().addingTimeInterval(40))
queryNative()
IOHIDManagerUnscheduleFromRunLoop(manager,CFRunLoopGetMain(),CFRunLoopMode.defaultMode.rawValue)
IOHIDManagerClose(manager,IOOptionBits(kIOHIDOptionsTypeNone))
if opened == kIOReturnSuccess { IOHIDDeviceClose(device,IOOptionBits(kIOHIDOptionsTypeNone)) }
// Process exit releases this diagnostic's BLE connection without unpairing.
let firmwareOK = ble.firmware.count == 3 && ble.firmware.allSatisfy { $0 == expected }
let hidOK = nativeSamples.count == 2 && nativeSamples.allSatisfy { ($0["a0"] == 0 || $0["a0"] == 1) && $0["b2"] == 0 }
let identityOK = ble.values["2A50"] == "014c0066020000" && ble.values["2A27"] == "31313030"
let inputObserved = inputOpen == kIOReturnSuccess && !inputCounts.isEmpty && inputErrors == 0
let summary: [String:Any] = ["registryOK":registryOK,"directFirmwareOK":firmwareOK,"identityOK":identityOK,
    "firmwareReads":ble.firmware,"gattValues":ble.values,"nativeStatusOK":hidOK,"nativeSamples":nativeSamples,
    "inputOpenResult":String(format:"0x%08x",UInt32(bitPattern:inputOpen)),"inputValueCounts":inputCounts,
    "inputCallbackErrors":inputErrors,"inputObserved":inputObserved,"bleErrors":ble.errors,"bleDisconnects":ble.disconnects,
    "limitations":["Input counts do not prove every button or touch coordinate is correct.","Gyro mode is not enabled or changed.","LG TV pointer behavior, IR, microphone, long-term stability and battery capacity are not covered."]]
if let data = try? JSONSerialization.data(withJSONObject:summary,options:[.sortedKeys]),let text = String(data:data,encoding:.utf8) {
    log("HEALTH_JSON="+text)
}
log("Direct firmware: \(firmwareOK ? "PASS" : "UNCONFIRMED/MISMATCH"); identity: \(identityOK ? "PASS" : "UNCONFIRMED/MISMATCH"); native status: \(hidOK ? "PASS" : "UNCONFIRMED/MISMATCH")")
log("Input counts: \(inputCounts); callback errors: \(inputErrors); BLE disconnects: \(ble.disconnects)")
log("Passive input observation: \(inputObserved ? "PASS (events received; individual controls not validated)" : "UNCONFIRMED (check permissions and operate the remote during observation)")")
log("No application SET, firmware payload, reset or pairing command was sent.")
exit(firmwareOK && hidOK && identityOK && ble.errors.isEmpty && inputObserved ? 0 : 4)

"""Separate native pairing experiment. Use LG's remote while input is stopped."""
import json
import os
import time
import uuid
from pathlib import Path
import native_bus
from graphics import Canvas
from transport import BluetoothBus
from flow import PairingFlow

APP = 'org.magicsirimote.pairingtest'
native_bus.APP = APP
ROOT = Path(__file__).resolve().parent


def main():
    os.umask(0o027)
    session = uuid.uuid4().hex
    state = ROOT / 'state'
    def record(value):
        value.update(session=session, uid=os.getuid(), version='0.1.6')
        data = json.dumps(value, indent=2) + '\n'
        temp = state / ('status-' + session + '.tmp')
        temp.write_text(data); temp.replace(state / 'status.json')
        (state / ('receipt-' + session + '.json')).write_text(data)
    canvas = None
    with native_bus.NativeBus() as life, BluetoothBus() as bus:
        flow = PairingFlow(bus, record)
        focus = 0; prepare_confirm = False; last_frame = 0; seen = set()
        def controls():
            if prepare_confirm: return ['Confirm re-pair', 'Cancel']
            if flow.phase == 'idle': return ['Read status', 'Close']
            if flow.phase == 'ready': return ['Prepare remote', 'Scan', 'Close']
            if flow.phase in ('prepared',): return ['Scan', 'Close']
            if flow.phase == 'scanning': return ['Finish scan', 'Close']
            if flow.phase == 'scanned': return ['Pair selected remote', 'Scan again', 'Close']
            return ['Close']
        def activate(label):
            nonlocal prepare_confirm, focus
            if label == 'Close': return False
            if label == 'Read status': flow.inspect()
            elif label == 'Prepare remote': prepare_confirm = True
            elif label == 'Confirm re-pair': prepare_confirm = False; flow.prepare()
            elif label == 'Cancel': prepare_confirm = False
            elif label in ('Scan', 'Scan again'): flow.scan()
            elif label == 'Finish scan': flow.stop_scan()
            elif label == 'Pair selected remote': flow.pair()
            focus = 0
            return True
        try:
            canvas = Canvas(APP)
            running = True
            while running:
                for event, params in life.events():
                    if event == 'close': running = False
                    elif event in ('registered', 'relaunch'):
                        canvas.restore()
                        # Installer-driven testing exposes only these explicit actions.
                        nonce = params.get('nonce')
                        if type(nonce) is str and nonce not in seen and len(nonce) <= 64:
                            seen.add(nonce)
                            action = params.get('pairingTest')
                            if action == 'inspect': flow.inspect(params.get('remoteAddress'))
                            elif action == 'prepare': flow.prepare()
                            elif action == 'scan': flow.scan()
                            elif action == 'scanAndPair': flow.scan_and_pair()
                            elif action == 'finishScan': flow.stop_scan()
                            elif action == 'pair': flow.pair()
                flow.tick()
                buttons = controls(); focus = min(focus, len(buttons) - 1)
                for kind, value in canvas.events():
                    if kind == 'close': running = False
                    elif kind == 'key':
                        if value in (27, 461, 1073742094):
                            if prepare_confirm: prepare_confirm = False
                            else: running = False
                        elif value == 1073741904: focus = (focus - 1) % len(buttons)
                        elif value == 1073741903: focus = (focus + 1) % len(buttons)
                        elif value in (1073741906, 1073741905) and flow.candidates:
                            flow.selected = (flow.selected + (1 if value == 1073741905 else -1)) % len(flow.candidates)
                        elif value in (13, 1073741912): running = activate(buttons[focus])
                    elif kind == 'click':
                        x, y = value
                        if 600 <= y <= 656:
                            index = (x - 60) // 380
                            if 0 <= index < len(buttons): running = activate(buttons[index])
                        elif 315 <= y < 525 and flow.candidates:
                            index = (y - 315) // 52
                            if 0 <= index < min(4, len(flow.candidates)): flow.selected = index
                if time.monotonic() - last_frame > .1:
                    last_frame = time.monotonic(); canvas.clear()
                    canvas.text('Magic Sirimote / Pairing Test', 60, 42, 34)
                    canvas.text('Separate test app - no IR assignments or motion sensor settings are written.', 60, 96, 22)
                    canvas.text('Status: ' + flow.phase, 60, 145, 26, (106, 201, 255))
                    canvas.text(flow.message, 60, 192, 24)
                    canvas.text('Remote: ' + (flow.target or 'Choose from fresh scan results'), 60, 244, 23)
                    if prepare_confirm:
                        canvas.text('This removes the selected remote pairing from the TV.', 60, 320, 25)
                        canvas.text('The main input app must already be stopped. IR settings are preserved.', 60, 365, 23)
                    else:
                        for i, device in enumerate(list(flow.candidates.values())[:4]):
                            y = 315 + i * 52
                            if i == flow.selected: canvas.rectangle((60, y, 1120, 46), (34, 82, 126))
                            canvas.text(device['name'] + '   ' + device['address'] + ('   (already paired)' if device['paired'] else ''), 75, y + 8, 23)
                    canvas.text('Use LG remote: Left/Right selects an action; Up/Down selects a device.', 60, 550, 21)
                    for i, label in enumerate(buttons):
                        canvas.rectangle((60 + i * 380, 600, 360, 56), (32, 125, 184) if i == focus else (44, 59, 75))
                        canvas.text(label, 78 + i * 380, 614, 23, max_width=325)
                    canvas.present()
                time.sleep(.02)
        finally:
            # Cancel our own subscriptions only; never stop global discovery or unpair on exit.
            if flow.phase not in ('success', 'failed', 'idle', 'ready', 'prepared', 'scanned'):
                flow.fail('Test closed before completion; inspect status before trying again')
            if canvas: canvas.close()


if __name__ == '__main__': main()

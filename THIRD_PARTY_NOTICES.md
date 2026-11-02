# Research references and third-party scope

The project is licensed under the root MIT `LICENSE`. The public export includes project-developed Python/JavaScript source, tests, and package-building helpers. It does not bundle TV firmware, LG native libraries, Node.js, Python, LLVM, captured Bluetooth traffic, diagnostic cable firmware, or whole upstream remote-control/homebrew packages.

The directory `src/runtime/vendor/` is a historical name for local helper snapshots carried forward from this project's earlier touch decoder. It is not an installation of the upstream `open-appleremote` package.

The following work informed the investigation and deserves credit:

| Project / source | Role in this work |
| --- | --- |
| [a-funk/open-appleremote](https://github.com/a-funk/open-appleremote), especially [PROTOCOL.md](https://github.com/a-funk/open-appleremote/blob/main/docs/PROTOCOL.md) | Remote protocol, activation, button and signed touch-coordinate references |
| [Yanndroid/SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux) | Earlier first-generation remote implementation and sensor-format references |
| [Razdva122/clean-your-tv-lg-webos](https://github.com/Razdva122/clean-your-tv-lg-webos) | Investigation of TV-local native helpers and webOS execution boundaries |
| [webosbrew/webos-homebrew-channel](https://github.com/webosbrew/webos-homebrew-channel) | Startup, service, and platform research references |
| [webosbrew/dev-manager-desktop](https://github.com/webosbrew/dev-manager-desktop) | Developer access and package-management tooling |
| [webosose/webos.service.bluetooth2](https://github.com/webosose/webos.service.bluetooth2) and [bluetooth-sil-api](https://github.com/webosose/bluetooth-sil-api) | Bluetooth service and lower-layer interface research |
| [webosose/luna-service2](https://github.com/webosose/luna-service2) | Platform service-bus implementation and interfaces |
| [LG webOS TV documentation](https://webostv.developer.lge.com/) | Developer Mode, CLI, and application model |

The original projects retain their own copyrights and licenses. Credit is not an assertion that their code or all their features are bundled, nor that their authors endorse this project. If contributing copied or adapted upstream code, identify the exact source and preserve the applicable notices in that contribution.

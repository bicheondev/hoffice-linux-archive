# QOffscreen RTTI/vtable map v3

Status: **PASS**

Exact prepatched plugin SHA-256: `8ba0ddb433ed8cb838013f833b11d62a0f02c481aa51b2d8193c7179e232dee6`

| Boundary | Exact address |
|---|---:|
| `backing-store-constructor` | `0x11270` |
| `create-backing-store` | `0x10040` |
| `create-platform-window` | `0x10390` |
| `flush` | `0x11410` |
| `integration-constructor` | `0x10210` |
| `integration-create` | `0xfd60` |
| `paint-device` | `0x11160` |
| `plugin-instance` | `0xfdd0` |
| `window-constructor` | `0x10ca0` |

This map proves only exact-binary target resolution. Dynamic guest execution remains gated by the v3 probe matrix.

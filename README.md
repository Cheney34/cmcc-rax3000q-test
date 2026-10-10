# RAX3000Q / RAX3000QY (ipq50xx) OpenWrt 自编译固件仓库

用 **GitHub Actions** 编译 CMCC RAX3000Q / RAX3000QY 的**可刷 UBI 固件**。
本仓库自带两条互相独立、可来回切换的构建流水线（互不影响，各自出产物）。

> 前置状态：你的机器**已经刷了 NWrt/第三方 U-Boot**，可以进 `192.168.1.1` 的 U-Boot 网页直接刷镜像。
> 见 [`docs/刷机教程.md`](docs/刷机教程.md)。

---

## 一、选哪条路线（先看结论）

**你的场景（校园网、千兆以内、要官方内核、越新越好）→ 只跑「轨道 A」，NSS 可以忽略。**

| | **轨道 A：官方主线（主推，建议只用这个）** | 轨道 B：QSDK 完整 NSS（可选实验） |
|---|---|---|
| 源码 | `openwrt/openwrt` **main**（默认最新 HEAD，可用 `ref` 固定提交） | `kkstone/immortalwrt-ipq50xx` `openwrt-21.02` |
| 内核 | **mainline Linux 6.x（最新）**，与官方 snapshot 同源 | QSDK **5.4**（2020 年的老内核，已停更） |
| 装包 | `apk add` 官方源包 —— **用户态包全都能装** | 只能 `opkg` 装 ImmortalWrt 21.02 的 `.ipk` |
| 高通 NSS | 无（官方主线也没把 offload 栈合进去） | **完整**：`kmod-qca-nss-dp` + `kmod-qca-nss-drv` + `qca-nss-fw-ipq50xx-retail`（target 默认内置），Wi-Fi/NAT 双 NSS |
| 转发性能 | 软件 flow offloading：**IPQ5018 双核 A53 在千兆线路上够用** | 卸载到 NPU，900+ Mbit/s 且 CPU 几乎不动 |
| IPv6 / Portal / LuCI 中文 / 改 MAC | ✅（同一套 `files/`） | ✅（同一套 `files/`） |
| 维护状态 | 官方在更，长期可用 | ImmortalWrt 21.02 已停更（fork 最后 push 2024-09） |
| 产物 | `*-squashfs-sysupgrade.bin` / `*-squashfs-factory.ubi` | `*-squashfs-nand-factory.bin` |

**为什么可以忽略 NSS：** 你的线路在千兆以内，而 NSS 的意义是把 NAT/Wi-Fi 转发卸载到 NPU —— 只有在「多千兆 + 大流量 + CPU 被转发打满」时才有明显收益。
官方主线用**软件 flow offloading**（`firewall.@defaults[0].flow_offloading=1`）转发千兆以内的流量没问题，
换来的是**新内核 + 官方长期维护 + 完整包生态**。所以本仓库默认只推荐轨道 A。

两条产物都能在你现有 U-Boot 网页里刷，随时互切，不用重刷引导。

### 关于内核版本（你要「官方 + 新一点」）

轨道 A 默认 `git clone` 官方 `main` 的**最新 HEAD**，所以内核比你看到的官方 snapshot（6.18.55）还要新。
工作流也支持在 Actions 页面填 `ref`（提交号或 tag）来固定版本：

- **要最新内核** → `ref` 留空（默认，跟 main 走）
- **要和官方 snapshot 的 kmod 完全对齐** → `ref` 填 `ae9276426c2e51ebba1732f952b0592ca8af24b6`（= 官方 `r37117`）

### 关于「官方 ipk」

**OpenWrt 25.12 / snapshot 已全面改用 `apk`，官方仓库里没有 `.ipk` 了**（`default_packages` 里是 `apk-mbedtls`，`opkg` 已消失）。
所以「装官方包」在今天的正确含义是 `apk add <包名>`，由轨道 A 提供；轨道 B 给的是 `.ipk` + `opkg`，但那是 ImmortalWrt 21.02 源，不是官方源。
详见 [`docs/路线对比与选型.md`](docs/路线对比与选型.md)。

---

## 二、怎么用（3 步）

1. **把本目录推到一个 GitHub 仓库**（可以是私有仓库）：
   ```bash
   cd rax3000q-ipq50xx-build
   git init && git add -A && git commit -m "init"
   git remote add origin git@github.com:<你的用户名>/rax3000q-ipq50xx-build.git
   git push -u origin main
   ```
2. **打开 Actions 页**，选工作流，点 `Run workflow`：
   - ✅ `Build OpenWrt (官方 mainline / 轨道 A)` → 产物 `openwrt-official-*` ← **主推，只跑这个就够**
     - `ref` 留空 = 官方 main 最新（内核最新）；填 `ae9276426c2e51ebba1732f952b0592ca8af24b6` = 官方 snapshot 同源
     - `enable_wifi` 默认 `true`：上游把 RAX3000Q 的 Wi-Fi 在 DTS 里关了（256 MiB RAM 防 OOM），工作流会自动打补丁重新打开
   - ⚙️ `Build ImmortalWrt QSDK NSS (轨道 B)` → 产物 `openwrt-qsdk-nss-*` ← 可选实验（老内核 5.4，只有想玩 NSS 才跑）
   - 首次编译约 2～4 小时（免费额度足够）。两个工作流也可同时跑。
3. **下载 Artifacts 里的镜像**，按 [`docs/刷机教程.md`](docs/刷机教程.md) 刷入。

编译失败时：工作流会保留完整日志；`-j1 V=s` 的降级重试已内置，并把 `.config` 与错误段落一起打进 artifact 便于定位。


---

## 三、固件里预置了什么

| 能力 | 实现 |
|---|---|
| **官方包兼容** | 轨道 A 不把任何 `kmod-*` 编进固件（内核配置保持官方原样），所以**用户态包**（LuCI、opennds、curl、工具…）都能从官方源 `apk add`；`kmod-*` 能否装取决于 `ref` 是否与官方快照同源 |
| **IPv6** | `wan6` = `dhcpv6` + `reqprefix auto`；LAN 下 RA/DHCPv6 `server`（M+O 位）；开 `odhcpd` 中继友好 |
| **Portal 网页认证** | `opennds`（内置 MHD 网页服务，**它本来就没有 LuCI 应用**）；首次启动由 `95-portal` 自动配好网关模式、一键上网票据、DNS/DHCP 放行；可改一行切到用户名/密码模式 |
| **LuCI 全中文** | `luci-i18n-*` 全量 + `luci.main.lang=zh-cn` |
| **改 MAC** | `/usr/sbin/rax-mac`：LAN / WAN / 2.4G / 5G 四口按基准 MAC 自动派生；**默认不写死**，只有 `/etc/mac_base` 存在时才覆盖（避免所有机器同一 MAC）|
| **转发性能** | 软件 flow offloading（`flow_offloading=1`，`flow_offloading_hw=0`）；IPQ5018 双核 A53 在千兆线路上够用，**不依赖 NSS** |
| **精简稳定** | 只保留必需包；不装 passwall/docker/编译器等大件 |

首次开机后访问 `http://192.168.1.1`，`root` / 空密码（**请立刻设置密码**）。

---

## 四、目录结构

```
rax3000q-ipq50xx-build/
├── .github/workflows/
│   ├── build-official.yml       # 轨道 A（主推）：官方 main + 最新内核 + 官方 apk 源
│   └── build-qsdk-nss.yml       # 轨道 B（可选实验）：ImmortalWrt 21.02 / QSDK 5.4 + 完整 NSS
├── common/                      # 各轨道共用的叠加文件系统
│   └── files/
│       ├── etc/uci-defaults/99-rax3000q-defaults   # 中文/时区/IPv6/软卸载/调 rax-mac
│       ├── etc/uci-defaults/95-portal              # openNDS 一键上网预配置
│       └── usr/sbin/rax-mac                        # 改 MAC 工具
├── official/                    # 轨道 A 专属
│   ├── config.seed              # 种子 .config（只写用户态包，绝不写 kmod）
│   └── scripts/enable-wifi.py   # 上游 DTS 把 Wi-Fi 关了 → 打补丁重新打开
├── qsdk/                        # 轨道 B 专属
│   ├── config.seed
│   └── files/
└── docs/
    ├── 刷机教程.md
    └── 路线对比与选型.md
```

## 五、许可与致谢

本项目只提供构建脚本与配置，不改动上游源码。
致谢 [OpenWrt](https://github.com/openwrt/openwrt)、[ImmortalWrt](https://github.com/immortalwrt/immortalwrt)、
[kkstone/Actions-OpenWrt-RAX3000Q](https://github.com/kkstone/Actions-OpenWrt-RAX3000Q)、
[sfxfs/rax3000qy-OpenWrt](https://github.com/sfxfs/rax3000qy-OpenWrt)（NWrt U-Boot 与刷机方法）、
[P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt)（Actions 骨架）。
